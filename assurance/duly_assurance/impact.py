"""Rule-change impact analysis over the golden corpus.

For every golden case, re-adjudicate under the *current working-tree* rule
pack (the path named in ``case.yaml``) and compare the fresh decision to the
committed golden receipt:

- a case **flips** when ``decision.value`` differs (an ``AdjudicationError``
  under the new pack counts as a flip to "no decision");
- a case has a **reasoning-only change** when the decision value is the same
  but the set of fired rule ids or their defeated sets differ.

Impact reports; it does not gate. Exit 0 whenever analysis completes,
exit 2 on operational errors (missing corpus, unloadable pack).

Deterministic by construction: no wall clock, no randomness, cases processed
in sorted order, all output orderings stable.

Usage:
    python -m duly_assurance impact [--golden golden] [--json out.json]
                                    [--markdown out.md]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from duly_kernel.api import adjudicate
from duly_kernel.engine import AdjudicationError
from duly_kernel.ir import PackValidationError, load_pack

from .corpus import PackNotFound, resolve_pack_path

MARKER = "<!-- duly-impact -->"
MAX_DETAILED_EXCERPTS = 5


class ImpactOperationalError(Exception):
    """The corpus or a pack could not be loaded; analysis cannot complete."""


# ---------------------------------------------------------------------------
# Corpus loading


def _load_case(case_dir: Path) -> dict:
    case_path = case_dir / "case.yaml"
    if not case_path.is_file():
        raise ImpactOperationalError(f"missing case.yaml in {case_dir}")
    try:
        with open(case_path, "r", encoding="utf-8") as f:
            case = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ImpactOperationalError(f"unreadable case.yaml in {case_dir}: {e}") from e
    if not isinstance(case, dict):
        raise ImpactOperationalError(f"case.yaml in {case_dir} is not a mapping")
    for field in ("pack", "asOfEffective", "asOfKnowledge"):
        if not case.get(field):
            raise ImpactOperationalError(f"case.yaml in {case_dir} missing '{field}'")
    case.setdefault("id", case_dir.name)
    return case


def _load_facts(case_dir: Path) -> list[dict]:
    facts_dir = case_dir / "facts"
    if not facts_dir.is_dir():
        raise ImpactOperationalError(f"missing facts/ directory in {case_dir}")
    facts: list[dict] = []
    for path in sorted(facts_dir.glob("*.json")):
        try:
            with open(path, "r", encoding="utf-8") as f:
                facts.append(json.load(f))
        except (OSError, json.JSONDecodeError) as e:
            raise ImpactOperationalError(f"unreadable fact {path}: {e}") from e
    if not facts:
        raise ImpactOperationalError(f"no facts in {facts_dir}")
    return facts


def _load_receipt(receipts_dir: Path, case_id: str) -> dict:
    path = receipts_dir / f"{case_id}.json"
    if not path.is_file():
        raise ImpactOperationalError(f"missing golden receipt {path}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise ImpactOperationalError(f"unreadable golden receipt {path}: {e}") from e


def _load_pack_cached(path: Path, cache: dict[Path, dict]) -> dict:
    key = path.resolve()
    if key not in cache:
        try:
            cache[key] = load_pack(key)
        except (OSError, PackValidationError, yaml.YAMLError) as e:
            raise ImpactOperationalError(f"unloadable pack {path}: {e}") from e
    return cache[key]


def _decision_attribute(case: dict, golden_receipt: dict, pack: dict) -> str:
    """The decision attribute to re-adjudicate: prefer the golden receipt's,
    else match the case question against the pack's declared decisions."""
    attr = golden_receipt.get("decision", {}).get("attribute")
    if attr:
        return attr
    question = case.get("question")
    decisions = pack.get("decisions", [])
    for d in decisions:
        if question and (d.get("question") == question or d.get("attribute") == question):
            return d["attribute"]
    if len(decisions) == 1:
        return decisions[0]["attribute"]
    raise ImpactOperationalError(
        f"cannot determine decision attribute for case {case.get('id')!r}"
    )


# ---------------------------------------------------------------------------
# Comparison


def _reasoning(receipt: dict) -> list[dict]:
    """Stable summary of the reasoning: fired rule ids with their defeated
    sets, sorted by rule id."""
    out = []
    for f in receipt.get("rulesFired", []):
        out.append({"ruleId": f["ruleId"], "defeated": sorted(f.get("defeated", []))})
    return sorted(out, key=lambda r: r["ruleId"])


def _fmt_value(value: dict | None) -> str:
    if value is None:
        return "no decision"
    v = value.get("value")
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def _side(value: dict | None, reasoning: list[dict], error: str | None = None) -> dict:
    side = {"value": value, "valueDisplay": _fmt_value(value), "rulesFired": reasoning}
    if error is not None:
        side["error"] = error
    return side


def analyze(golden_root: Path, *, pack_overrides: dict[Path, dict] | None = None) -> dict:
    """Run impact analysis over the corpus at `golden_root`.

    Returns the full machine-readable report. Raises ImpactOperationalError
    when the corpus or any pack cannot be loaded.

    `pack_overrides` maps a resolved pack path to a pack dict to use *instead
    of* the file on disk. The CLI never passes it — reading the working tree is
    the point of the command. It exists for callers holding a candidate pack
    that is not (and may never be) a file: the demo's Rule Studio asks "what
    would this edit flip" before the edit is written anywhere, which is the
    only order in which the answer can change the author's mind.
    """
    cases_dir = golden_root / "cases"
    receipts_dir = golden_root / "receipts"
    if not cases_dir.is_dir():
        raise ImpactOperationalError(f"missing golden corpus: {cases_dir} is not a directory")
    case_dirs = sorted(d for d in cases_dir.iterdir() if d.is_dir())
    # An empty corpus is not an error. An adopter's corpus is empty on day one,
    # and `verify` has always treated that as success — reserving failure for a
    # *missing* directory, which is a configuration mistake rather than a state.
    # `impact` used to raise here, so the two commands disagreed about the same
    # input and an adopter's first CI run failed on the second of them.
    #
    # What the caller must not be allowed to conclude is that nothing flipped.
    # rulepacks/README.md already names this trap one level down: a pack with no
    # generator template gets a cheerful "0 of N decisions flip" forever. Silence
    # that reads as coverage is the failure mode, so callers get an explicit
    # `corpusEmpty` flag and every renderer says so in words.

    # Seeding the cache is the whole override mechanism: every case that
    # resolves to this path gets the candidate pack, and a case pointing
    # somewhere else is unaffected, so a draft is measured against exactly the
    # corpus slice it governs.
    pack_cache: dict[Path, dict] = dict(pack_overrides or {})
    flips: list[dict] = []
    reasoning_changes: list[dict] = []
    unchanged: list[str] = []

    for case_dir in case_dirs:
        case = _load_case(case_dir)
        case_id = str(case["id"])
        facts = _load_facts(case_dir)
        golden = _load_receipt(receipts_dir, case_id)
        try:
            pack_path = resolve_pack_path(str(case["pack"]), golden_root)
        except PackNotFound as e:
            raise ImpactOperationalError(str(e)) from e
        pack = _load_pack_cached(pack_path, pack_cache)
        attribute = _decision_attribute(case, golden, pack)

        before_value = golden.get("decision", {}).get("value")
        before_reasoning = _reasoning(golden)

        error: str | None = None
        new_receipt: dict | None = None
        try:
            new_receipt = adjudicate(
                facts,
                pack,
                str(case["asOfEffective"]),
                str(case["asOfKnowledge"]),
                attribute,
            )
        except AdjudicationError as e:
            error = str(e)

        entry_base = {
            "caseId": case_id,
            "question": case.get("question", ""),
            "pack": str(case["pack"]),
        }
        if error is not None:
            flips.append({
                **entry_base,
                "before": _side(before_value, before_reasoning),
                "after": _side(None, [], error=f"AdjudicationError: {error}"),
            })
            continue

        after_value = new_receipt.get("decision", {}).get("value")
        after_reasoning = _reasoning(new_receipt)
        if after_value != before_value:
            flips.append({
                **entry_base,
                "before": _side(before_value, before_reasoning),
                "after": _side(after_value, after_reasoning),
            })
        elif after_reasoning != before_reasoning:
            reasoning_changes.append({
                **entry_base,
                "value": before_value,
                "before": _side(before_value, before_reasoning),
                "after": _side(after_value, after_reasoning),
            })
        else:
            unchanged.append(case_id)

    total = len(case_dirs)
    return {
        "golden": str(golden_root),
        "corpusEmpty": total == 0,
        "totalCases": total,
        "flipCount": len(flips),
        "reasoningChangeCount": len(reasoning_changes),
        "unchangedCount": len(unchanged),
        "summary": _summary_line(len(flips), total, len(reasoning_changes)),
        "flips": flips,
        "reasoningChanges": reasoning_changes,
        "unchanged": unchanged,
    }


EMPTY_CORPUS_SUMMARY = (
    "NO CASES IN CORPUS — impact analysis could not see anything. "
    "This is not a result: it means nothing was measured."
)


def _summary_line(flip_count: int, total: int, reasoning_count: int) -> str:
    # "0 of 0 decisions flip" is a true sentence that reads as a pass. Say what
    # actually happened instead; the exit code stays 0 so a day-one adopter is
    # not blocked, and the words are what stop silence being mistaken for
    # coverage (rulepacks/README.md names the same trap for an uncovered pack).
    if total == 0:
        return EMPTY_CORPUS_SUMMARY
    return (
        f"{flip_count} of {total} decisions flip; "
        f"{reasoning_count} reasoning-only change{'s' if reasoning_count != 1 else ''}"
    )


# ---------------------------------------------------------------------------
# Rendering


def _md_escape(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _md_rules(side: dict) -> str:
    fired = side.get("rulesFired", [])
    if not fired:
        return "none"
    parts = []
    for f in fired:
        defeated = ", ".join(f["defeated"]) if f["defeated"] else "none"
        parts.append(f"`{f['ruleId']}` (defeated: {defeated})")
    return "; ".join(parts)


def render_markdown(report: dict) -> str:
    lines = [MARKER, "## Rule-change impact analysis", ""]
    if report.get("corpusEmpty"):
        lines.append(f"**{report['summary']}**")
        lines.append("")
        lines.append(
            "No golden cases were found, so this run measured nothing. A green "
            "check here is not evidence that a change is safe."
        )
        return "\n".join(lines)
    lines.append(f"**{report['summary']}** ({report['totalCases']} golden cases analyzed)")
    lines.append("")

    flips = report["flips"]
    if flips:
        lines.append("### Flipped decisions")
        lines.append("")
        lines.append("| Case | Question | Before | After |")
        lines.append("| --- | --- | --- | --- |")
        for flip in flips:
            after = flip["after"]
            after_display = after["valueDisplay"]
            if after.get("error"):
                after_display = f"no decision ({_md_escape(after['error'])})"
            lines.append(
                f"| `{_md_escape(flip['caseId'])}` "
                f"| {_md_escape(flip['question'])} "
                f"| `{flip['before']['valueDisplay']}` "
                f"| `{after_display}` |"
            )
        lines.append("")
        lines.append("### Before/after details")
        lines.append("")
        for flip in flips[:MAX_DETAILED_EXCERPTS]:
            lines.append(f"#### `{_md_escape(flip['caseId'])}`")
            lines.append("")
            lines.append(
                f"- **Before**: decision `{flip['before']['valueDisplay']}`; "
                f"rules fired: {_md_rules(flip['before'])}"
            )
            after = flip["after"]
            if after.get("error"):
                lines.append(
                    f"- **After**: no decision — {_md_escape(after['error'])}"
                )
            else:
                lines.append(
                    f"- **After**: decision `{after['valueDisplay']}`; "
                    f"rules fired: {_md_rules(after)}"
                )
            lines.append("")
        if len(flips) > MAX_DETAILED_EXCERPTS:
            lines.append(
                f"_...and {len(flips) - MAX_DETAILED_EXCERPTS} more flipped "
                f"case{'s' if len(flips) - MAX_DETAILED_EXCERPTS != 1 else ''} "
                f"(see the JSON report for full detail)._"
            )
            lines.append("")
    else:
        lines.append("No decisions flip under this change.")
        lines.append("")

    lines.append(
        f"**Reasoning-only changes**: {report['reasoningChangeCount']} "
        f"(same decision, different rules fired or defeated sets)"
    )
    if report["reasoningChanges"]:
        ids = ", ".join(f"`{c['caseId']}`" for c in report["reasoningChanges"])
        lines.append("")
        lines.append(f"Affected cases: {ids}")
    lines.append("")
    return "\n".join(lines)


def render_text(report: dict) -> str:
    lines = [report["summary"]]
    for flip in report["flips"]:
        after = flip["after"]
        after_display = after["valueDisplay"]
        if after.get("error"):
            after_display = f"no decision ({after['error']})"
        lines.append(
            f"  FLIP {flip['caseId']}: {flip['before']['valueDisplay']} -> {after_display}"
        )
    for change in report["reasoningChanges"]:
        lines.append(f"  REASONING {change['caseId']}: decision unchanged, rules differ")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m duly_assurance impact",
        description="Report which golden decisions flip under the working-tree rule packs.",
    )
    parser.add_argument("--golden", default="examples/golden", help="golden corpus root (default: examples/golden)")
    parser.add_argument("--json", dest="json_out", default=None, metavar="OUT.JSON",
                        help="write the full machine-readable report")
    parser.add_argument("--markdown", dest="markdown_out", default=None, metavar="OUT.MD",
                        help="write the PR-comment markdown body")
    args = parser.parse_args(argv)

    try:
        report = analyze(Path(args.golden))
    except ImpactOperationalError as e:
        print(f"impact: error: {e}", file=sys.stderr)
        return 2

    print(render_text(report))

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, sort_keys=True, ensure_ascii=False)
            f.write("\n")
    if args.markdown_out:
        with open(args.markdown_out, "w", encoding="utf-8") as f:
            f.write(render_markdown(report))

    return 0
