"""What the demo renders for the *teaching* packs.

The example content's own tests (see `exampletest_helpers`): they run while
`examples/` exists, they are deleted with it, and CI runs them as
`uv run pytest examples/tests -q`.

Extracted from `demo/tests/test_api.py`, whose `_pack()` helper had already
been converted to the toolkit's own `fixtures/pack.yaml` — leaving exactly the
tests that passed it a *name*, i.e. the ones whose subject genuinely is a
committed pack. Those are here.

Verdict wording is pack data (CLAUDE.md, "Demo discipline"): `_determination`
resolves a decision's `phrasing:` block server-side, so every string asserted
below is a claim about the pack file, not about `demo/app.py`. The renderer's
own contract — the Yes/No fallback, the honest `attribute = value` degradation,
placeholder resolution — stays in `demo/tests/test_api.py` on the fixture pack.

No `DULY_DEMO_CONTENT` is set here. The demo's default content root is this
directory's parent, so importing `demo.app` serves the teaching content
exactly as a plain `uvicorn demo.app:app` does.
"""

from __future__ import annotations

import sys

import yaml

from exampletest_helpers import REPO_ROOT, RULEPACKS

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from demo.app import _determination, _render_answer  # noqa: E402


def _pack(name: str) -> dict:
    """A committed teaching pack, loaded as the demo loads it.

    Determination tests build their scenario around a *real* pack because the
    wording under test lives in the pack's `phrasing:` block, not in
    `demo/app.py` — fabricating one inline would only test the renderer.
    """
    path = RULEPACKS / name / "pack.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _scenario(pack_name: str, facts: list[dict] | None = None) -> dict:
    return {"pack": _pack(pack_name), "facts": facts or []}


def test_render_answer_describes_tolerance_cure_as_a_determination():
    receipt = {
        "decision": {
            "attribute": "trid:toleranceCureAmount",
            "value": {"kind": "money", "amount": "250.00", "currency": "USD"},
        },
        "asOf": {"effective": "2026-07-29T00:00:00Z"},
    }

    scenario = _scenario("trid-fee-tolerance-us-federal")
    answer = _render_answer(receipt, scenario, "2026-07-29")

    assert answer == "Cure required: 250.00 USD tolerance cure as of 2026-07-29."
    assert _determination(receipt, scenario, "2026-07-29") == {
        "verdict": "Cure required",
        "detail": "250.00 USD tolerance cure",
        "tone": "warn",
    }


def test_rescission_deadline_cross_checks_the_printed_notice_date():
    """The deadline is computed by the kernel; the date printed on the notice
    is only a cross-check. Agreement is stated, disagreement warns — and in
    both cases the computed date is the verdict."""
    receipt = {
        "decision": {
            "attribute": "resc:rescissionDeadline",
            "value": {"kind": "date", "value": "2026-05-27"},
        },
        "asOf": {"effective": "2026-05-26T00:00:00Z"},
    }
    printed_ok = _scenario(
        "tila-rescission-us-federal",
        [
            {
                "attribute": "resc:statedRescissionDeadline",
                "value": {"kind": "date", "value": "2026-05-27"},
            }
        ],
    )
    found = _determination(receipt, printed_ok, "2026-05-26")
    assert found["verdict"] == "Midnight of 2026-05-27"
    assert "matches the deadline printed on the notice" in found["detail"]
    assert found["tone"] == ""

    misprinted = _scenario(
        "tila-rescission-us-federal",
        [
            {
                "attribute": "resc:statedRescissionDeadline",
                "value": {"kind": "date", "value": "2026-05-24"},
            }
        ],
    )
    found = _determination(receipt, misprinted, "2026-05-26")
    assert found["verdict"] == "Midnight of 2026-05-27"
    assert "notice prints 2026-05-24" in found["detail"]
    assert found["tone"] == "warn"

    # No printed-date fact at all: no cross-check claim either way.
    found = _determination(receipt, _scenario("tila-rescission-us-federal"), "2026-05-26")
    assert found["verdict"] == "Midnight of 2026-05-27"
    assert "printed" not in found["detail"]
    assert found["tone"] == ""


def test_every_placeholder_the_validator_accepts_is_one_the_demo_renders():
    """The two halves of the phrasing contract must not drift apart.

    `validate_pack` owns the vocabulary (a pack author's typo has to fail
    where the pack loads); `demo/app.py` owns the rendering. A placeholder the
    kernel blesses and the renderer cannot resolve would silently discard a
    template alternative instead of erroring.

    Run against the notice pack because the fact-, derived- and
    date-arithmetic placeholders need a decision with those shapes underneath
    it; the fixture pack has no derived intermediate to name.
    """
    from duly_kernel.ir import validate_pack

    receipt = {
        "decision": {
            "attribute": "nc:noticeCompliant",
            "value": {"kind": "money", "amount": "45.00", "currency": "USD"},
        },
        "asOf": {"effective": "2026-07-29T00:00:00Z"},
        "abstentions": [
            {
                "attribute": "nc:noticeMailedDate",
                "reason": "low_confidence",
                "confidence": {"score": 0.62},
                "threshold": {"minConfidence": 0.75},
            }
        ],
        "derivation": {
            "conclusion": {"attribute": "nc:noticeCompliant"},
            "premises": [
                {
                    "conclusion": {
                        "attribute": "nc:requiredMinimumNoticeDays",
                        "value": {"kind": "decimal", "value": "45"},
                    },
                    "premises": [],
                }
            ],
        },
    }
    facts = [
        {"attribute": "nc:noticeMailedDate", "value": {"kind": "date", "value": "2026-07-25"}},
        {
            "attribute": "nc:policyExpirationDate",
            "value": {"kind": "date", "value": "2026-09-01"},
        },
    ]
    templates = [
        "{value}",
        "{value|day}",
        "{value|int}",
        "{money}",
        "{caveat}",
        "{fact:noticeMailedDate}",
        "{fact:noticeMailedDate|day}",
        "{derived:requiredMinimumNoticeDays}",
        "{derived:requiredMinimumNoticeDays|int}",
        "{daysBetween:noticeMailedDate,policyExpirationDate}",
    ]
    scenario = _scenario("termination-notice-us-states", facts)
    for template in templates:
        pack = _pack("termination-notice-us-states")
        for decision in pack["decisions"]:
            if decision["attribute"] == "nc:noticeCompliant":
                decision["phrasing"] = [{"verdict": template}]
        validate_pack(pack)  # the kernel accepts it …
        found = _determination(receipt, {"pack": pack, "facts": facts}, "2026-07-29")
        assert not found.get("generic"), template  # … and the renderer resolves it
        assert found["verdict"], template
    assert scenario["pack"]["decisions"]  # sanity: the committed pack still parses


def test_every_committed_pack_phrases_every_decision_it_advertises():
    """A pack that advertises a question must be able to phrase its answer.

    Boolean decisions may rely on the Yes/No fallback; anything else needs a
    `phrasing:` block, or the demo would render a bare value. Sweeping the
    packs here means a new pack is covered the moment it lands.
    """
    non_boolean = {
        "nc:requiredMinimumNoticeDays",
        "trid:toleranceCureAmount",
        "trid:toleranceCategory",
        "pkg:signingMethod",
        "resc:rescissionDeadline",
        "rec:requiredFirstPageTopSpaceInches",
        "rec:sb2FeeDueUSD",
    }
    pack_files = sorted(RULEPACKS.glob("*/pack.yaml"))
    assert pack_files, f"no committed packs under {RULEPACKS}"
    seen = set()
    for pack_file in pack_files:
        pack = yaml.safe_load(pack_file.read_text(encoding="utf-8"))
        for decision in pack.get("decisions") or []:
            attribute = decision["attribute"]
            seen.add(attribute)
            assert decision.get("phrasing"), (pack_file.parent.name, attribute)
    assert non_boolean <= seen
