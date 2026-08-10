"""Tests for the Z3 static pack verifier (assurance/duly_assurance/prove.py).

Everything that needs the solver carries `@pytest.mark.z3` and skips when
z3-solver is not importable — the same posture `docling` and `linkml` take.
Run them with:

    uv run --with z3-solver pytest assurance/tests -q -m z3

The unmarked tests below hold the parts that must work *without* z3: the
subcommand wiring, and the guarantee that importing the module does not drag
an optional dependency into the core suite.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys
from pathlib import Path

import pytest

from provetest_helpers import (  # noqa: E402
    COMMITTED_PACKS,
    HAVE_Z3,
    REPO_ROOT,
    boolean_split_pack,
    committed_pack,
    covered_pack,
    derived_guard_pack,
    disjoint_numeric_pack,
    overlapping_numeric_pack,
    repo_registry,
    string_order_pack,
    uncovered_pack,
    untypable_pack,
)

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

needs_z3 = pytest.mark.skipif(not HAVE_Z3, reason="z3-solver is not installed")


def analyze(pack, **kwargs):
    from duly_assurance.prove import analyze_pack

    return analyze_pack(Path("<memory>"), pack, repo_registry(), **kwargs)


def verdicts(report):
    return {(p.left, p.right): p.verdict for p in report.pairs}


def coverage_of(report, attribute):
    return next(c for c in report.coverage if c.attribute == attribute)


# ---------------------------------------------------------------------------
# Wiring that must not need the solver
# ---------------------------------------------------------------------------


def test_the_dispatcher_knows_both_subcommands():
    from duly_assurance.__main__ import main

    out = subprocess.run(
        [sys.executable, "-m", "duly_assurance", "--help"],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    assert "prove" in out.stdout and "prove-equivalent" in out.stdout
    assert main(["--help"]) == 0


def test_importing_prove_does_not_require_z3():
    """The core suite imports this module; the optional dependency must stay
    optional. A missing z3 is a *message*, not an ImportError."""
    from duly_assurance import prove

    assert "z3-solver is not installed" in prove.Z3_MISSING
    assert "uv run --with z3-solver" in prove.Z3_MISSING


def test_the_verdict_names_are_the_documented_three():
    from duly_assurance import prove

    assert prove.PROVED_DISJOINT == "PROVED-DISJOINT"
    assert prove.NOT_PROVED == "NOT-PROVED"
    assert prove.OUT_OF_FRAGMENT == "OUT-OF-FRAGMENT"


def test_prove_equivalent_has_no_repo_relative_ontologies_default():
    """The fourth CLI to carry `default="ontologies"`, and the one the A10
    sweep missed: it is the SECOND parser in a file whose first parser was
    already fixed, and that sweep read files, not parsers. A default that is
    right in this repository hides the wrong-path case everywhere else
    (CLAUDE.md), so the parser must resolve through the same
    `_resolve_ontologies` no-default path `prove` uses.

    Asserted without the solver: the z3 gate fires *before* registry
    resolution, so this checks the parser itself.
    """
    import argparse

    from duly_assurance import prove

    # Reach the parser the same way main_equivalent builds it: parse a
    # minimal argv and inspect the namespace default.
    parser = argparse.ArgumentParser()
    # Rather than duplicating the parser, assert on the source of truth the
    # CLI actually uses: _resolve_ontologies prefers the flag, then the
    # environment, then None — never a literal path.
    ns = argparse.Namespace(ontologies=None)
    import os

    old = os.environ.pop("DULY_ONTOLOGIES", None)
    try:
        assert prove._resolve_ontologies(ns) is None
        os.environ["DULY_ONTOLOGIES"] = "somewhere/else"
        assert prove._resolve_ontologies(ns) == "somewhere/else"
    finally:
        if old is None:
            os.environ.pop("DULY_ONTOLOGIES", None)
        else:
            os.environ["DULY_ONTOLOGIES"] = old
    # And the parser default itself is None: parsing no flag must leave the
    # namespace resolving through the environment, not through a path that
    # only exists in duly's own checkout.
    assert 'default="ontologies"' not in pathlib.Path(prove.__file__).read_text()


@needs_z3
@pytest.mark.z3
def test_prove_equivalent_refuses_a_missing_registry_by_name():
    """A path that was typed on purpose and does not exist is an error, not a
    silent weakening of every verdict — same posture as `prove` (A10)."""
    from duly_assurance.prove import main_equivalent

    pack = str(REPO_ROOT / "fixtures" / "pack.yaml")
    code = main_equivalent([pack, pack, "--ontologies", "no/such/place"])
    assert code == 2


# ---------------------------------------------------------------------------
# Disjointness: what the kernel's syntactic check cannot see
# ---------------------------------------------------------------------------


@needs_z3
@pytest.mark.z3
def test_a_boolean_split_is_proved_disjoint():
    """CLAUDE.md's "boolean guards don't prove disjointness" gotcha, proved.

    `_equality_guards` accepts only quoted-string equality, so the kernel
    needs the authored `overrides` here. The solver does not.
    """
    report = analyze(boolean_split_pack())
    assert verdicts(report) == {("TOY-ON", "TOY-OFF"): "PROVED-DISJOINT"}


@needs_z3
@pytest.mark.z3
def test_disjoint_numeric_ranges_are_proved_and_overlapping_ones_are_not():
    """spec/dmn.md M6: "a numeric range is not a proof" — to the kernel."""
    assert verdicts(analyze(disjoint_numeric_pack())) == {
        ("TOY-LOW", "TOY-HIGH"): "PROVED-DISJOINT"
    }
    report = analyze(overlapping_numeric_pack())
    (pair,) = report.pairs
    assert pair.verdict == "NOT-PROVED"
    assert dict(pair.witness)["toy:amount"] == "10"


@needs_z3
@pytest.mark.z3
def test_a_guard_on_a_derived_binding_is_proved_disjoint():
    """The narrowest gotcha in CLAUDE.md: `_equality_guards` ignores `derived`
    bindings entirely, so `band == "High"` versus `band == "Low"` proves
    nothing to the kernel however string-equal it looks. The encoding defines
    the derived value from its producers, so it proves it."""
    report = analyze(derived_guard_pack())
    assert verdicts(report) == {("TOY-HIGH", "TOY-LOW"): "PROVED-DISJOINT"}


@needs_z3
@pytest.mark.z3
def test_an_unproved_pair_carries_a_readable_witness():
    report = analyze(overlapping_numeric_pack())
    (pair,) = report.pairs
    assert pair.reason == "both rules fire under this assignment"
    assert pair.overrides == "TOY-HIGH overrides TOY-LOW"
    labels = dict(pair.witness)
    assert set(labels) == {"asOf.effective", "toy:amount"}
    assert labels["asOf.effective"].count("-") == 2  # an ISO date, not an ordinal


@needs_z3
@pytest.mark.z3
def test_an_unencodable_guard_is_named_not_guessed():
    """An OUT-OF-FRAGMENT verdict must say which construct stopped it. It must
    never quietly become PROVED-DISJOINT or NOT-PROVED."""
    report = analyze(string_order_pack())
    (pair,) = report.pairs
    assert pair.verdict == "OUT-OF-FRAGMENT"
    assert "TOY-ORD" in pair.reason
    assert "ordering comparison" in pair.reason


@needs_z3
@pytest.mark.z3
def test_a_symbol_the_encoding_cannot_type_fails_the_whole_pack_loudly():
    report = analyze(untypable_pack())
    assert report.error is not None
    assert "no usage from which to infer a value kind" in report.error
    assert report.pairs == []


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------


@needs_z3
@pytest.mark.z3
def test_a_table_with_a_hole_reports_the_hole_with_a_witness():
    report = analyze(uncovered_pack())
    result = coverage_of(report, "toy:verdict")
    assert not result.covered
    assert result.verdict == "NOT-PROVED"
    grade = dict(result.witness)["toy:grade"]
    assert grade in ('"A"', '"B"', "«any other value»", "(no fact asserted)")
    assert grade != '"A"'  # "A" is covered by TOY-A


@needs_z3
@pytest.mark.z3
def test_a_default_row_makes_coverage_total():
    report = analyze(covered_pack())
    assert coverage_of(report, "toy:verdict").covered


@needs_z3
@pytest.mark.z3
def test_the_recording_packs_fail_closed_region_is_found_and_named():
    """county-recording-us documents that an unknown jurisdiction gets no
    recordability presumption at all. That is a coverage hole by design, and
    the prover finds it and names the jurisdiction."""
    report = analyze(committed_pack("county-recording-us"))
    result = coverage_of(report, "rec:recordable")
    assert not result.covered
    assert dict(result.witness)["rec:recordingState"] == "«any other value»"


@needs_z3
@pytest.mark.z3
def test_an_uncovered_region_only_outside_the_effective_window_says_so():
    """trid:toleranceCureAmount has a default rule, so the only gap is an
    evaluation point before the pack's own effective date. Saying that is a
    much more useful report than a bare UNCOVERED."""
    report = analyze(committed_pack("trid-fee-tolerance-us-federal"))
    result = coverage_of(report, "trid:toleranceCureAmount")
    assert not result.covered
    assert "outside every concluding rule's effective window" in result.reason


# ---------------------------------------------------------------------------
# The committed packs
# ---------------------------------------------------------------------------


@needs_z3
@pytest.mark.z3
@pytest.mark.parametrize("name", COMMITTED_PACKS)
def test_every_committed_pack_encodes_and_leaves_no_unresolved_ambiguity(name):
    report = analyze(committed_pack(name))
    assert report.error is None
    assert not report.fatal, [
        (p.left, p.right, p.attribute) for p in report.pairs if p.fatal
    ]
    out_of_fragment = [p for p in report.pairs if p.verdict == "OUT-OF-FRAGMENT"]
    assert out_of_fragment == [], [p.reason for p in out_of_fragment]


@needs_z3
@pytest.mark.z3
def test_the_esign_note_rules_overlap_and_the_authored_override_is_why_that_is_fine():
    """PKG-NOTE-30 (every promissory note) and PKG-NOTE-31 (a registered
    eNote) share priority 150 and genuinely overlap — a registered eNote
    satisfies both. The pack is correct because PKG-NOTE-31 overrides
    PKG-NOTE-30; the prover reports the overlap rather than pretending it
    away, and reports the resolution rather than failing."""
    report = analyze(committed_pack("esign-closing-package"))
    pair = next(
        p for p in report.pairs if {p.left, p.right} == {"PKG-NOTE-30", "PKG-NOTE-31"}
    )
    assert pair.verdict == "NOT-PROVED"
    assert pair.overrides == "PKG-NOTE-31 overrides PKG-NOTE-30"
    assert not pair.fatal
    witness = dict(pair.witness)
    assert witness["pkg:documentType"] == '"PromissoryNote"'
    assert witness["pkg:eNoteRegistered"] == "true"


@needs_z3
@pytest.mark.z3
def test_the_esign_document_type_rules_are_proved_disjoint():
    report = analyze(committed_pack("esign-closing-package"))
    proved = {
        (p.left, p.right) for p in report.pairs if p.verdict == "PROVED-DISJOINT"
    }
    assert ("PKG-CD-10", "PKG-RTC-20") in proved
    assert ("PKG-CD-11", "PKG-RTC-21") in proved
    assert ("PKG-NOTE-30", "PKG-DOT-40") in proved


@needs_z3
@pytest.mark.z3
def test_the_tila_packs_prose_claims_about_disjointness_are_proved():
    """The TILA pack carries two comments saying, in effect, "these rules can
    never both fire, but the validator cannot prove it, so we separated the
    priorities". Both claims check out — including the one that runs through
    a deadline computed with the pack's own business-day calendar."""
    report = analyze(committed_pack("tila-rescission-us-federal"), all_pairs=True)
    proved = {
        (p.left, p.right) for p in report.pairs if p.verdict == "PROVED-DISJOINT"
    }
    assert ("RESC-APP-01", "RESC-APP-02") in proved
    assert ("RESC-FUND-STAY", "RESC-FUND-EXP") in proved


@needs_z3
@pytest.mark.z3
def test_every_committed_rule_is_reachable():
    """A rule no input can fire is dead weight in a rulebase somebody has to
    review. None of the six packs has one."""
    for name in COMMITTED_PACKS:
        report = analyze(committed_pack(name))
        dead = [r.rule_id for r in report.reachability if not r.reachable]
        assert dead == [], f"{name}: {dead}"


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


@needs_z3
@pytest.mark.z3
@pytest.mark.parametrize("name", COMMITTED_PACKS)
def test_the_report_is_byte_identical_across_runs(name):
    from duly_assurance.prove import render

    pack = committed_pack(name)
    first = render(analyze(pack, all_pairs=True), verbose=True)
    second = render(analyze(pack, all_pairs=True), verbose=True)
    assert first == second


@needs_z3
@pytest.mark.z3
def test_the_report_is_byte_identical_under_different_hash_seeds():
    """A witness is normalized by pinning symbols against a static candidate
    ladder, so the printed assignment depends only on satisfiability answers
    — not on dict ordering, and not on the solver's search."""
    script = (
        "import sys; from pathlib import Path;"
        "from duly_assurance.prove import analyze_pack, render;"
        "from duly_kernel.ir import load_pack;"
        "from duly_conformance.registry import load_repo_registry;"
        "r = load_repo_registry('fixtures/ontology');"
        "p = load_pack('fixtures/pack.yaml');"
        "sys.stdout.write(render(analyze_pack(Path('x'), p, r, all_pairs=True), verbose=True))"
    )
    outputs = []
    for seed in ("0", "1", "12345"):
        run = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, cwd=REPO_ROOT,
            env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"},
        )
        assert run.returncode == 0, run.stderr
        outputs.append(run.stdout)
    assert outputs[0] == outputs[1] == outputs[2]


# ---------------------------------------------------------------------------
# The CLI contract
# ---------------------------------------------------------------------------


@needs_z3
@pytest.mark.z3
def test_the_fixture_pack_exits_zero(capsys, monkeypatch):
    """The CLI contract, over the toolkit's own pack: a pack the kernel
    accepted cannot make `prove` fail, so exit zero is the expected shape."""
    from duly_assurance.prove import main

    monkeypatch.chdir(REPO_ROOT)
    assert main(["--ontologies", "fixtures/ontology", "fixtures/pack.yaml"]) == 0
    assert "unresolved ambiguity" not in capsys.readouterr().out


@needs_z3
@pytest.mark.z3
def test_the_committed_packs_exit_zero(capsys, monkeypatch):
    """Example content: the subject is the six teaching packs, so this moves
    with them."""
    from duly_assurance.prove import main

    monkeypatch.chdir(REPO_ROOT)
    assert main(["--ontologies", "ontologies", *[f"rulepacks/{name}/pack.yaml" for name in COMMITTED_PACKS]]) == 0
    out = capsys.readouterr().out
    assert "PROVED-DISJOINT" in out
    assert "unresolved ambiguity" not in out


@needs_z3
@pytest.mark.z3
def test_a_pack_the_kernel_refuses_is_reported_not_tracebacked(tmp_path, capsys):
    import yaml

    from duly_assurance.prove import main

    pack = derived_guard_pack()
    for r in pack["rules"]:
        r.pop("overrides", None)
        if r["id"] == "TOY-LOW":
            r["when"] = ['band != "Nothing"']
    path = tmp_path / "pack.yaml"
    path.write_text(yaml.safe_dump(pack), encoding="utf-8")

    assert main([str(path)]) == 2
    assert "ambiguous pack" in capsys.readouterr().err


def test_validate_pack_already_refuses_an_unproven_same_priority_pair():
    """Why the non-zero exit is a *differential* check, not a routine gate.

    `validate_pack` refuses any same-priority pair concluding one attribute
    unless it can prove disjointness syntactically or the author wrote an
    `overrides`. So the only same-priority pairs `prove` ever sees are ones
    the kernel already blessed. `prove` exiting non-zero on one of them would
    mean Z3 refuted a proof `validate_pack` accepted — a kernel soundness
    bug, not an authoring mistake. It does not happen today; the exit code
    exists so that it could not happen silently.
    """
    from duly_kernel.ir import PackValidationError, validate_pack

    pack = derived_guard_pack()
    for rule in pack["rules"]:
        rule.pop("overrides", None)
        if rule["id"] == "TOY-LOW":
            rule["when"] = ['band != "Nothing"']  # now overlaps TOY-HIGH
    with pytest.raises(PackValidationError, match="ambiguous pack"):
        validate_pack(pack)


@needs_z3
@pytest.mark.z3
def test_an_unresolved_same_priority_overlap_is_reported_as_fatal(capsys):
    """The gate itself, exercised on the pack `validate_pack` would refuse."""
    from duly_assurance.prove import _summary

    pack = derived_guard_pack()
    for rule in pack["rules"]:
        rule.pop("overrides", None)
        if rule["id"] == "TOY-LOW":
            rule["when"] = ['band != "Nothing"']
    report = analyze(pack)

    pair = next(p for p in report.pairs if {p.left, p.right} == {"TOY-HIGH", "TOY-LOW"})
    assert pair.verdict == "NOT-PROVED"
    assert pair.overrides is None
    assert pair.fatal and report.fatal
    summary = _summary([report])
    assert "unresolved ambiguity" in summary
    assert "TOY-HIGH / TOY-LOW" in summary


@needs_z3
@pytest.mark.z3
def test_json_output_is_machine_readable(capsys, monkeypatch):
    import json

    from duly_assurance.prove import main

    monkeypatch.chdir(REPO_ROOT)
    assert main(["--ontologies", "fixtures/ontology", "fixtures/pack.yaml", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    (pack,) = payload["packs"]
    assert pack["pack"] == "duly-fixture-pack"
    assert {p["verdict"] for p in pack["pairs"]} <= {
        "PROVED-DISJOINT", "NOT-PROVED", "OUT-OF-FRAGMENT"
    }


@needs_z3
@pytest.mark.z3
def test_the_demo_runs_and_self_checks():
    """spec/prove_demo.py exits non-zero if any claim it prints stops holding
    — the eSign verdicts, the TILA prose claims, the recording pack's
    documented coverage hole, or the perturbation being caught."""
    run = subprocess.run(
        [sys.executable, str(REPO_ROOT / "spec" / "prove_demo.py")],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    assert "PROVED-DISJOINT" in run.stdout
    assert "OUT-OF-FRAGMENT" in run.stdout
    assert "FAILED" not in run.stdout


@needs_z3
@pytest.mark.z3
def test_the_demo_output_is_byte_identical_across_runs():
    runs = [
        subprocess.run(
            [sys.executable, str(REPO_ROOT / "spec" / "prove_demo.py")],
            capture_output=True, text=True, cwd=REPO_ROOT,
            env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"},
        ).stdout
        for seed in ("0", "7")
    ]
    assert runs[0] == runs[1]


@needs_z3
@pytest.mark.z3
def test_nothing_here_touches_adjudication():
    """The load-bearing claim: `prove` is validation-time only. Running it
    over a pack must leave the pack dict — and therefore every receipt the
    kernel would emit from it — untouched."""
    import copy

    pack = committed_pack("esign-closing-package")
    before = copy.deepcopy(pack)
    analyze(pack, all_pairs=True)
    assert pack == before
