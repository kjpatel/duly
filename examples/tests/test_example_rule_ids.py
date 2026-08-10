"""The committed teaching packs' rule ids, and the grandfather list they pin.

The example content's own tests (see `exampletest_helpers`): they run while
`examples/` exists, they are deleted with it, and CI runs them as
`uv run pytest examples/tests -q`.

Extracted from `kernel/tests/test_rule_ids.py`, which keeps the convention's
unit tests — what a conforming id is, which shapes `validate_pack` refuses,
how a pack opts in — asserted against synthetic packs built in the test. Those
are toolkit. What moved here sweeps the six committed packs and the exemption
list in `duly_kernel.rule_ids`, whose contents are a claim about *those packs*:
`NY-NR-45` is grandfathered because it sits in 76 golden receipts, and both
the receipts and the pack are example content.

`GRANDFATHERED_RULE_IDS` itself stays in the kernel. It has to: an id is
permanent because it is sealed into receipts that already exist, so the
exemption outlives any particular corpus. What is asserted here is only the
reconciliation between that list and the packs currently committed — which is
exactly the part that stops being true when the packs go.
"""

from __future__ import annotations

import yaml

from duly_kernel.ir import load_pack
from duly_kernel.rule_ids import (
    GRANDFATHERED_RULE_ID_COUNT,
    GRANDFATHERED_RULE_IDS,
    rule_id_problem,
)

from exampletest_helpers import RULEPACKS


def committed_packs():
    """Every committed teaching pack, as (path, parsed pack).

    The list-then-assert shape is the vacuous-glob guard: an empty directory
    must fail these tests loudly, not let two of them pass over nothing while
    the other two fail confusingly.
    """
    packs = [
        (pack_file, yaml.safe_load(pack_file.read_text(encoding="utf-8")))
        for pack_file in sorted(RULEPACKS.glob("*/pack.yaml"))
    ]
    assert packs, "no committed packs found; these tests sweep example content"
    return packs


def test_every_committed_pack_declares_its_id_family():
    for pack_file, pack in committed_packs():
        assert pack["pack"].get("idPrefix"), pack_file.name


def test_the_grandfather_list_is_exactly_the_ids_that_predate_the_convention():
    """Every committed id is listed, nothing else is, and the count is pinned.

    The list is the exemption's whole audit trail: it may only grow in a diff
    that also changes this count.
    """
    committed = {
        pack["pack"]["name"]: {r["id"] for r in pack["rules"]}
        for _, pack in committed_packs()
    }
    assert set(GRANDFATHERED_RULE_IDS) == set(committed)
    for name, ids in committed.items():
        assert GRANDFATHERED_RULE_IDS[name] == frozenset(ids), name
    total = sum(len(ids) for ids in GRANDFATHERED_RULE_IDS.values())
    assert total == GRANDFATHERED_RULE_ID_COUNT == 46


def test_seventeen_of_the_grandfathered_ids_would_fail_the_convention_today():
    """The honest measure of what the exemption is carrying.

    Every one of these is a receipt-visible id that cannot be renamed: a
    jurisdiction-first prefix, a year, a statute section, or a day count.
    """
    non_conforming = {}
    for _, pack in committed_packs():
        prefix = pack["pack"]["idPrefix"]
        for r in pack["rules"]:
            problem = rule_id_problem(r, prefix)
            if problem:
                non_conforming[r["id"]] = problem
    assert set(non_conforming) == {
        # county-recording-us — jurisdiction-first, and two encoded lengths
        "CA-TOPSPACE-25",
        "AZ-TOPMARGIN-20",
        "CA-DTT-11933",
        "CA-SB2-75",
        "CA-SB2-EXEMPT-DTT",
        # notarization-ron-us-states — jurisdiction-first, year-suffixed
        "VA-RON-2012",
        "TX-RON-2018",
        "FL-RON-2020",
        "NY-RON-2023",
        "CA-RON-2030",
        # termination-notice-us-states — jurisdiction-first, day counts
        "NY-NR-45-LEGACY",
        "NY-NR-45",
        "NY-NR-NONPAY-15",
        "FL-NR-120",
        "FL-NONPAY-10",
        "CA-NR-75",
        "CA-NONPAY-10",
    }
    assert len(non_conforming) == 17


def test_the_committed_packs_still_load():
    """Grandfathering is not a promise unless the packs actually validate."""
    for pack_file, _ in committed_packs():
        load_pack(pack_file)
