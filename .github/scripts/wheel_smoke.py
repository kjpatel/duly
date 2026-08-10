#!/usr/bin/env python3
"""Does every shipped package actually work outside this repository?

Run against an installed wheel, from a directory that is not the repo:

    python .github/scripts/wheel_smoke.py

`examples/minimal-integration/check_wheel.sh` proves the *example* runs from a
wheel, which covers `duly_kernel` and `duly_conformance` and nothing else. That
gap is not theoretical: `duly_review` shipped reading the grounded-fact schema
from `<package>/../../spec/schemas/`, a path that exists in a git checkout and
in no wheel ever built, so `ReviewQueue.resolve()` raised `FileNotFoundError`
for every adopter — and every test in this repository passed, because in a
checkout the path is real (M5 finding A8; CHANGELOG.md, v1.0.0).

So this touches one genuine entry point per package. It is a smoke test, not a
test suite: the suites are thorough and run in the repo, where all of duly's
files are present. What only this can catch is a package that *needs* a file
the wheel does not carry.

Deliberately not covered: `duly_whatif` needs the optional `z3-solver`, and a
smoke test that installs a 36 MB solver stops being smoke.

That exclusion used to carry a second justification — "it has no repo-relative
file reads" — which was wrong, and wrong in the way this script exists to
catch. Its CLI resolved a case's pack against `parents[2]` of the installed
package and defaulted `--ontologies` to duly's own directory (M5 plan, A9);
neither is a read at import, which is why the claim survived, and both are the
assumption that duly's checkout is the content. Both are fixed. The solver size
is now the whole reason, and it is a real one — but a package excluded for cost
is not a package known to be clean.

Exit 0 if every check passes or is a known-and-declared failure; 1 otherwise.
"""

from __future__ import annotations

import pathlib
import sys
import traceback

# Known failures, with the finding that owns them. A check listed here is
# *expected* to fail and does not fail the run — but if it starts passing, the
# run fails anyway, so the entry cannot outlive the bug it documents.
# Empty, and that is the state to keep it in. It held `duly_review` for
# exactly one PR: the queue read the grounded-fact schema from a repo-relative
# path no wheel contains (A8). The schemas now ship inside `duly_core`, so the
# check passes and the entry had to go — an XPASS fails the run, which is how a
# known-failure is prevented from outliving its bug.
KNOWN_FAILURES: dict[str, str] = {}

CHECKS: list[tuple[str, str]] = []


def check(package: str):
    def register(fn):
        CHECKS.append((package, fn))
        return fn

    return register


@check("duly_core")
def _core():
    from duly_core import canonical, content_hash

    assert canonical({"b": 1, "a": 2}) == b'{"a":2,"b":1}'
    assert len(content_hash({"caseId": "c1"}, "contentHash")) == 64


@check("duly_kernel")
def _kernel():
    from duly_kernel import adjudicate, seal_fact

    fact = seal_fact({
        "caseId": "c1",
        "entity": {"id": "e:1", "type": "sm:Thing"},
        "attribute": "sm:flag",
        "value": {"kind": "boolean", "value": True},
        "grounding": {"kind": "attestation", "actor": "a", "at": "2026-01-01T00:00:00Z"},
        "assertion": {"kind": "human", "at": "2026-01-01T00:00:00Z", "actor": {"id": "a"}},
        "recordedAt": "2026-01-01T00:00:00Z",
        "status": "asserted",
        "schemaRef": {"ontology": "smoke", "version": "1.0.0"},
    })
    pack = {
        "pack": {"name": "smoke", "version": "1.0.0"},
        "decisions": [{"attribute": "sm:ok", "entityType": "sm:Thing"}],
        "rules": [{
            "id": "SM-DEFAULT-00", "version": "1.0.0", "priority": 0,
            "citation": {"text": "smoke"}, "effectiveFrom": "2020-01-01",
            "given": {"t": {"entityType": "sm:Thing"}},
            "then": {"entity": "t", "attribute": "sm:ok",
                     "value": {"kind": "boolean", "value": True}},
        }],
    }
    receipt = adjudicate([fact], pack, "2026-06-01", "2026-06-01T00:00:00Z", "sm:ok")
    assert receipt["decision"]["value"] == {"kind": "boolean", "value": True}


@check("duly_store")
def _store():
    from duly_store.store import FactStore

    store = FactStore(":memory:")
    store.init_schema()


@check("duly_conformance")
def _conformance():
    from duly_conformance import OntologyRegistry, check_fact, parse_ontology

    ontology = parse_ontology({
        "name": "smoke", "version": "1.0.0",
        "prefixes": {"sm": "https://example.invalid/sm#"},
        "classes": {"Thing": {"class_uri": "sm:Thing", "attributes": {
            "flag": {"slot_uri": "sm:flag", "range": "boolean"}}}},
    })
    registry = OntologyRegistry([ontology])
    issues = check_fact({
        "id": "urn:duly:fact:sha256:" + "0" * 64,
        "entity": {"id": "e:1", "type": "sm:Thing"},
        "attribute": "sm:flag",
        "value": {"kind": "boolean", "value": True},
        "schemaRef": {"ontology": "smoke", "version": "1.0.0"},
    }, registry)
    assert issues == [], issues


@check("duly_calibration")
def _calibration():
    from duly_calibration import TemperatureCalibrator

    # T=1 is the identity, so this asserts the maths runs, not a fitted value.
    assert abs(TemperatureCalibrator().apply(0.8, {"temperature": 1.0}) - 0.8) < 1e-9


@check("duly_extraction")
def _extraction():
    from duly_extraction.stub import StubAdapter

    assert StubAdapter is not None


@check("duly_assurance")
def _assurance():
    """An empty corpus is an adopter's day one, and must not be an error."""
    import tempfile
    from pathlib import Path

    from duly_assurance.impact import analyze

    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "cases").mkdir()
        (Path(tmp) / "receipts").mkdir()
        report = analyze(Path(tmp))
    assert report["corpusEmpty"] is True


@check("duly_dmn")
def _dmn():
    from duly_dmn import DmnCompileError, compile_source

    try:
        compile_source("<definitions/>")
    except DmnCompileError:
        pass  # refusing malformed input is the entry point working


@check("duly_review")
def _review():
    """The queue's schema load, which is where A8 bit."""
    import tempfile
    from pathlib import Path

    from duly_review.queue import ReviewQueue, _default_fact_schema

    with tempfile.TemporaryDirectory() as tmp:
        queue = ReviewQueue(str(Path(tmp) / "q.db"))
        queue.init_schema()
        assert _default_fact_schema()["title"] == "GroundedFact"


@check("duly_demo")
def _demo():
    """Importing the app mounts `static/`, so this is the wheel carrying it.

    The demo's four surfaces are Python plus a directory of pages, scripts,
    stylesheets and fonts that no import statement mentions. `StaticFiles`
    raises at mount time when that directory is absent, and the mount happens
    in `duly_demo.app`'s module body — so a wheel that shipped the code and
    dropped the assets fails right here, which is the only place it can.
    """
    from duly_demo.app import app

    assert app is not None


def _refuse_if_running_from_the_source_tree() -> None:
    """This script is only meaningful against an installed wheel.

    Run from a checkout every path it probes resolves, so it would report
    success for exactly the bugs it exists to find — and the known failures
    below would XPASS and fail the run for the wrong reason.
    """
    import duly_kernel

    if (pathlib.Path(duly_kernel.__file__).resolve().parents[2] / "pyproject.toml").exists():
        print(
            "refusing to run from duly's source tree: every repo-relative path "
            "resolves here, so this check can only pass. Build a wheel, install "
            "it into a clean venv, and run this from outside the repository "
            "(see .github/workflows/minimal-integration.yml).",
            file=sys.stderr,
        )
        raise SystemExit(2)


def main() -> int:
    _refuse_if_running_from_the_source_tree()
    failures: list[str] = []
    unexpected_passes: list[str] = []

    for package, fn in CHECKS:
        known = KNOWN_FAILURES.get(package)
        try:
            fn()
        except Exception:
            if known:
                print(f"xfail {package:18} (known: {known})")
            else:
                failures.append(package)
                print(f"FAIL  {package}")
                traceback.print_exc()
            continue
        if known:
            unexpected_passes.append(package)
            print(f"XPASS {package:18} — expected to fail but did not")
        else:
            print(f"ok    {package}")

    if unexpected_passes:
        print(
            "\nThese passed while listed as known failures: "
            f"{', '.join(unexpected_passes)}. Remove them from KNOWN_FAILURES — "
            "an entry that outlives its bug hides the next one.",
            file=sys.stderr,
        )
        return 1
    if failures:
        print(f"\n{len(failures)} package(s) do not work from a wheel: "
              f"{', '.join(failures)}", file=sys.stderr)
        return 1
    print("\nEvery shipped package works from an installed wheel.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
