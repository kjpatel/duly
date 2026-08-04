"""The replay guarantee is scoped to semantics, and something has to enforce it.

[spec/compatibility.md](../../spec/compatibility.md) C3 promises that a receipt
sealed under semantics version V replays byte-identically under any kernel
implementing V. The failure mode that clause exists to prevent is not a loud
one: it is a kernel implementing V2 replaying a V1 receipt and *passing*, on
the subset of cases where the two semantics happen to agree. That licenses a
claim the kernel is not entitled to make, and no byte comparison catches it —
the bytes match.

So the check is on the *claim*, before any adjudication runs.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from duly_kernel.receipt import SEMANTICS_VERSION
from duly_kernel.semantics import (
    IMPLEMENTED,
    UnsupportedSemantics,
    check_replayable,
    implements,
    receipt_semantics,
)

GOLDEN_RECEIPTS = Path(__file__).resolve().parents[2] / "golden" / "receipts"


@pytest.fixture()
def receipt() -> dict:
    return json.loads((GOLDEN_RECEIPTS / "notice-ny-0007.json").read_text())


def test_the_kernel_implements_exactly_the_version_it_emits():
    """A second entry is a promise that this code reproduces both versions
    byte-for-byte, which only the corpus can substantiate — so it is not a
    thing to add while tidying."""
    assert IMPLEMENTED == frozenset({SEMANTICS_VERSION})


def test_a_receipt_at_the_implemented_version_is_replayable(receipt):
    assert receipt_semantics(receipt) == SEMANTICS_VERSION
    check_replayable(receipt)  # does not raise


def test_a_receipt_at_another_version_is_refused(receipt):
    mutated = copy.deepcopy(receipt)
    mutated["engine"]["version"] = "0.0.2"
    with pytest.raises(UnsupportedSemantics) as excinfo:
        check_replayable(mutated)
    message = str(excinfo.value)
    assert "0.0.2" in message, "the refusal must name the version it refused"
    assert SEMANTICS_VERSION in message, "and what it does implement"
    assert excinfo.value.claimed == "0.0.2"


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda r: r.pop("engine"), id="no-engine-block"),
        pytest.param(lambda r: r["engine"].pop("version"), id="no-version"),
        pytest.param(lambda r: r["engine"].__setitem__("version", None), id="null-version"),
        pytest.param(lambda r: r.__setitem__("engine", "0.0.1"), id="engine-not-an-object"),
    ],
)
def test_a_receipt_that_names_no_semantics_is_refused(receipt, mutate):
    """Not defaulted to this kernel's. A receipt that does not say whose
    semantics it claims cannot be replayed under a promise scoped to them."""
    mutated = copy.deepcopy(receipt)
    mutate(mutated)
    with pytest.raises(UnsupportedSemantics, match="does not name"):
        check_replayable(mutated)


def test_implements_is_exact_not_a_prefix_or_a_range():
    """Semantics versions are handles, not an ordering claim: `0.0.10` is not
    a later `0.0.1`, and there is no such thing as compatible-within-a-minor
    here."""
    assert implements(SEMANTICS_VERSION)
    for near in ("0.0.10", "0.0", "0.0.1.0", "v0.0.1", "0.0.1 ", ""):
        assert not implements(near), near
    assert not implements(None)


def test_every_committed_receipt_passes_the_guard():
    """The guard is inert against the corpus — it must be, since all 351 were
    sealed under the one version that has ever existed. A guard that changed a
    verdict here would be a defect in the guard."""
    receipts = sorted(GOLDEN_RECEIPTS.glob("*.json"))
    assert len(receipts) == 351
    for path in receipts:
        check_replayable(json.loads(path.read_text()))
