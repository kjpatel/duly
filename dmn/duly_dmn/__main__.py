"""CLI: python -m duly_dmn <compile|verify|describe> ...

compile  — DMN decision tables -> a rule-IR pack.yaml (stdout, or -o FILE).
verify   — recompile a .dmn and compare against an already-committed
           pack.yaml; exit 1 on drift. This is what keeps a committed
           compilation honest in CI without a build step.
describe — print what the compiler read: hit policies, columns and their
           bindings, and the citation each row carries. Use it to check the
           annotation columns landed where you think they did before
           wondering why a rule will not compile.

Every failure is a DmnCompileError naming the decision, the row and the cell.
Exit codes: 0 success, 1 drift (verify), 2 compile error.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .compiler import compile_file
from .emit import emit_pack
from .errors import DmnCompileError
from .reader import read_file

EXIT_OK = 0
EXIT_DRIFT = 1
EXIT_COMPILE_ERROR = 2


_ROOT_MARKERS = ("pyproject.toml", ".git")


def _source_label(path: Path) -> str:
    """The `# Source:` header line.

    Anchored on the project root *above the .dmn file* — found by walking up
    for a `pyproject.toml` or `.git` — rather than on this module's location
    or on the cwd. The header is part of the compiled bytes, so it must not
    move when the repo is checked out elsewhere, when the compiler is invoked
    with an absolute path instead of a relative one, or when `duly_dmn` is
    installed non-editably into site-packages. Falls back to the bare
    filename when there is no project root to anchor on."""
    resolved = path.resolve()
    for parent in resolved.parents:
        if any((parent / marker).exists() for marker in _ROOT_MARKERS):
            return resolved.relative_to(parent).as_posix()
    return resolved.name


def _value_kinds(ontologies: str | None) -> dict[str, str]:
    """Attribute CURIE -> duly value kind, from an ontology directory.

    Optional, and deliberately so: the compiler's subject is DMN, not
    vocabulary. Supplying it lets the compiler refuse the one cell DMN cannot
    self-diagnose — a bare number tested against a money column. Without it
    that cell compiles and fails at adjudication instead.

    `duly_conformance` is imported here rather than at module scope so the
    compiler keeps working when only part of the toolkit is installed.
    """
    if not ontologies:
        return {}
    from duly_conformance import load_repo_registry

    kinds: dict[str, str] = {}
    for ontology in load_repo_registry(ontologies):
        for klass in ontology.classes.values():
            for slot in klass.slots.values():
                kinds[slot.curie] = slot.kind
    return kinds


def _cmd_compile(args) -> int:
    pack = compile_file(args.dmn, _value_kinds(args.ontologies))
    text = emit_pack(pack, source=_source_label(Path(args.dmn)))
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        rules = len(pack["rules"])
        print(
            f"compiled {rules} rule(s) across {len(pack['decisions'])} decision(s) "
            f"-> {args.output}",
            file=sys.stderr,
        )
    else:
        sys.stdout.write(text)
    return EXIT_OK


def _cmd_verify(args) -> int:
    pack = compile_file(args.dmn)
    expected = emit_pack(pack, source=_source_label(Path(args.dmn)))
    target = Path(args.pack)
    if not target.exists():
        print(f"FAIL  {target} does not exist; run `compile -o {target}`.")
        return EXIT_DRIFT
    actual = target.read_text(encoding="utf-8")
    if actual == expected:
        print(f"ok    {target} matches {args.dmn} ({len(pack['rules'])} rule(s)).")
        return EXIT_OK
    print(f"FAIL  {target} is not what {args.dmn} compiles to.")
    import difflib

    diff = difflib.unified_diff(
        actual.splitlines(keepends=True),
        expected.splitlines(keepends=True),
        fromfile=str(target),
        tofile=f"{args.dmn} (recompiled)",
    )
    sys.stdout.writelines(diff)
    return EXIT_DRIFT


def _cmd_describe(args) -> int:
    from .compiler import ANN_CITATION, ANN_EFFECTIVE_FROM, ANN_RULE_ID

    defs = read_file(args.dmn)
    print(f"DMN {defs.dmn_version}  pack={defs.pack.get('name')}@{defs.pack.get('version')}")
    for decision in defs.decisions:
        table = decision.table
        print(f"\ndecision {decision.id!r}  hitPolicy={table.hit_policy}")
        print(f"  concludes {decision.attribute} on {decision.entity_type} "
              f"as {decision.value_kind}")
        for column in table.inputs:
            print(f"  input  {column.label:<16} <- {column.expression}")
        print(f"  output {'<value>':<16} -> {decision.attribute}")
        for row in table.rows:
            rid = row.annotations.get(ANN_RULE_ID) or "<no duly:ruleId>"
            cite = row.annotations.get(ANN_CITATION) or "<no duly:citation>"
            eff = row.annotations.get(ANN_EFFECTIVE_FROM) or "<no duly:effectiveFrom>"
            cells = " | ".join(c or "-" for c in row.input_entries)
            print(f"  row {row.index}  {rid}  [{cells}]  -> {row.output_entry}")
            print(f"          {eff}  {cite}")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="duly-dmn", description=__doc__.splitlines()[0]
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_compile = sub.add_parser("compile", help="compile a .dmn into a rule-IR pack.yaml")
    p_compile.add_argument("dmn")
    p_compile.add_argument("-o", "--output", help="write to FILE instead of stdout")
    p_compile.add_argument(
        "--ontologies",
        help="directory of <name>/<version>.yaml ontologies the pack pins. "
        "Optional; supplying it lets the compiler reject a bare number tested "
        "against a money-valued column, which otherwise compiles and fails at "
        "adjudication.",
    )
    p_compile.set_defaults(func=_cmd_compile)

    p_verify = sub.add_parser("verify", help="check a committed pack.yaml against its .dmn")
    p_verify.add_argument("dmn")
    p_verify.add_argument("pack")
    p_verify.set_defaults(func=_cmd_verify)

    p_describe = sub.add_parser("describe", help="show what the compiler read")
    p_describe.add_argument("dmn")
    p_describe.set_defaults(func=_cmd_describe)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except DmnCompileError as e:
        print(f"{e}", file=sys.stderr)
        return EXIT_COMPILE_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
