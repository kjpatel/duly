"""`decision_digest()` — the determinant boundary, as code rather than prose.

Three layers, and they check different things on purpose.

**The vectors** ([spec/decision-digest-vectors.json](../../spec/decision-digest-vectors.json))
are the interop artifact: self-contained receipts and the digests they must
produce, reproducible by an implementation in another language that has neither
this kernel nor this corpus. Two of them are real committed receipts, and that
is asserted here — a vector file whose "real" receipts have drifted into
plausible fabrications would still pass every internal check.

**The equivalence relation** is checked as a relation, not as nine constants:
vectors sharing a class must agree, vectors in different classes must differ.
That is the claim spec/compatibility.md C4 actually makes, and a table of
digests does not state it.

**The corpus aggregate** is the regression net: one digest over every receipt in
[`fixtures/`](../../fixtures/README.md), catching any change to the determinant
set or the canonical form. It is a *different* failure signal from replay, which
compares whole receipts — a change that moves only excluded fields breaks replay
and must leave this untouched.

All three run against the toolkit's own fixture corpus rather than `golden/`.
The kernel's behaviour is not a property of the teaching content, and a test
that stops running when `examples/` is deleted would report success by
disappearing.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from duly_core import canonical
from duly_kernel.digest import DETERMINANT_FIELDS, decision_digest, determinant_projection

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_RECEIPTS = REPO_ROOT / "fixtures" / "receipts"
VECTORS_PATH = REPO_ROOT / "spec" / "decision-digest-vectors.json"

VECTORS = json.loads(VECTORS_PATH.read_text())["vectors"]


# --- the committed vectors --------------------------------------------------


@pytest.mark.parametrize(
    "vector", VECTORS, ids=[v["equivalenceClass"] + str(i) for i, v in enumerate(VECTORS)]
)
def test_every_vector_reproduces_its_committed_digest(vector):
    assert decision_digest(vector["receipt"]) == vector["decisionDigest"]


def test_the_vectors_claiming_to_be_committed_receipts_are_committed_receipts():
    """Otherwise the interop artifact drifts into a fabrication that still
    passes every check that only reads the file."""
    claimed = [v for v in VECTORS if "unmodified" in v["description"]]
    assert len(claimed) == 2, "expected two real receipts among the vectors"
    for vector in claimed:
        case_id = str(vector["receipt"]["caseId"]).rsplit(":", 1)[-1]
        committed = json.loads((FIXTURE_RECEIPTS / f"{case_id}.json").read_text())
        assert vector["receipt"] == committed, case_id


def test_vectors_in_one_class_agree_and_vectors_across_classes_do_not():
    """The relation, checked as a relation. This is the claim; the individual
    digests are only how it is expressed."""
    by_class: dict[str, set[str]] = {}
    for vector in VECTORS:
        by_class.setdefault(vector["equivalenceClass"], set()).add(
            decision_digest(vector["receipt"])
        )
    for name, digests in by_class.items():
        assert len(digests) == 1, f"class {name} disagrees with itself: {digests}"
    singletons = [next(iter(d)) for d in by_class.values()]
    assert len(set(singletons)) == len(singletons), "two classes share a digest"


# --- what the digest is over ------------------------------------------------


@pytest.fixture()
def receipt() -> dict:
    return json.loads((FIXTURE_RECEIPTS / "fx-0003.json").read_text())


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda r: r.__setitem__("caseId", "case:other:x"), id="caseId"),
        pytest.param(lambda r: r.__setitem__("id", "urn:duly:receipt:sha256:" + "0" * 64), id="id"),
        pytest.param(lambda r: r.__setitem__("receiptSha256", "0" * 64), id="receiptSha256"),
        pytest.param(lambda r: r["rulePack"].__setitem__("gitCommit", "abc1234"), id="gitCommit"),
        pytest.param(lambda r: r["rulePack"].__setitem__("url", "https://x.invalid"), id="url"),
        pytest.param(lambda r: r["engine"].__setitem__("backend", "clingo"), id="backend"),
        pytest.param(lambda r: r["engine"].__setitem__("kernel", "acme"), id="kernel"),
    ],
)
def test_a_field_that_identifies_the_run_does_not_move_the_digest(receipt, mutate):
    before = decision_digest(receipt)
    mutated = copy.deepcopy(receipt)
    mutate(mutated)
    assert mutated != receipt, "the mutation did nothing; the test proves nothing"
    assert decision_digest(mutated) == before


@pytest.mark.parametrize("field", DETERMINANT_FIELDS)
def test_every_determinant_field_moves_the_digest(receipt, field):
    """A field in the determinant set that the digest ignores is the defect
    this catches: the list would say one thing and the function another."""
    before = decision_digest(receipt)
    mutated = copy.deepcopy(receipt)
    mutated[field] = ["mutated"] if isinstance(mutated[field], list) else {"mutated": True}
    assert decision_digest(mutated) != before


@pytest.mark.parametrize(
    "path", [("rulePack", "name"), ("rulePack", "version"), ("engine", "version")]
)
def test_the_determinant_sub_fields_move_the_digest(receipt, path):
    before = decision_digest(receipt)
    mutated = copy.deepcopy(receipt)
    mutated[path[0]][path[1]] = "changed"
    assert decision_digest(mutated) != before


@pytest.mark.parametrize("field", ["decision", "engine", "rulePack", "abstentions"])
def test_a_receipt_missing_a_determinant_field_is_refused(receipt, field):
    """Silently digesting a partial document produces a confident answer about
    something that never happened."""
    mutated = copy.deepcopy(receipt)
    del mutated[field]
    with pytest.raises(KeyError, match=field):
        decision_digest(mutated)


def test_the_projection_is_the_hashed_input(receipt):
    """The digest is inspectable: a number nobody can argue with is not what
    this function is for."""
    projection = determinant_projection(receipt)
    assert decision_digest(receipt) == hashlib.sha256(canonical(projection)).hexdigest()
    assert set(projection) == set(DETERMINANT_FIELDS) | {"rulePack", "engine"}
    assert set(projection["rulePack"]) == {"name", "version"}
    assert set(projection["engine"]) == {"version"}


# --- the corpus -------------------------------------------------------------

#: SHA-256 over the newline-joined digests of every fixture receipt, in case-id
#: order. Regenerate deliberately: this moving means the determinant set or the
#: canonical form changed, which is a breaking change to the digest (C4), not a
#: corpus event. `verify` is what notices a corpus event.
CORPUS_AGGREGATE = "c0361067e2f84939b4bcb1c08e8a72e8120825d8adac63733758d587be54b90f"


def _corpus_aggregate() -> tuple[str, int]:
    receipts = sorted(FIXTURE_RECEIPTS.glob("*.json"))
    digests = [decision_digest(json.loads(p.read_text())) for p in receipts]
    joined = "\n".join(digests).encode("utf-8")
    return hashlib.sha256(joined).hexdigest(), len(digests)


def test_every_fixture_receipt_has_a_stable_digest():
    aggregate, count = _corpus_aggregate()
    assert count == 4
    assert aggregate == CORPUS_AGGREGATE, (
        "decision digests over the fixture corpus moved. If `fixtures/build.py` "
        "reproduces the receipts unchanged, the corpus did not move and the "
        "digest definition did — a breaking change to spec/compatibility.md C4."
    )


def test_the_demo_is_executed_not_merely_present():
    """spec/compatibility_demo.py asserts every claim it prints and exits
    non-zero if one stops holding — the same posture as prove_demo and
    whatif_demo. A demonstration nobody runs is a screenshot."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "spec" / "compatibility_demo.py")],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "refuses semantics it does not implement" in result.stdout


def test_no_two_fixture_receipts_share_a_digest():
    """Not a property the digest promises — two genuinely identical
    adjudications *should* collide — but these three decide differently, so a
    collision here means a determinant field stopped being determinant."""
    receipts = sorted(FIXTURE_RECEIPTS.glob("*.json"))
    digests = [decision_digest(json.loads(p.read_text())) for p in receipts]
    assert len(set(digests)) == len(digests)
