"""Which attributes a decision can consult (duly_kernel.relevance).

The question this answers is presentational — nothing here reaches a receipt —
but it must be answered *once*, because two surfaces disagreeing about whether
an exclusion is relevant is the same class of defect as two surfaces wording
one decision two ways.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from duly_kernel.relevance import consulted_attributes  # noqa: E402


def _rule(rule_id, concludes, given):
    return {
        "id": rule_id,
        "version": "1.0.0",
        "priority": 0,
        "citation": {"text": "Inline fixture (fictional)"},
        "effectiveFrom": "1900-01-01",
        "given": given,
        "then": {"entity": "thing", "attribute": concludes,
                 "value": {"kind": "boolean", "value": True}},
    }


PACK = {
    "pack": {"name": "relevance-fixture", "version": "1.0.0"},
    "rules": [
        _rule("A-01", "fx:answer", {
            "thing": {"entityType": "fx:Thing"},
            "direct": {"attribute": "fx:direct"},
            "step": {"derived": "fx:middle"},
        }),
        _rule("M-01", "fx:middle", {
            "thing": {"entityType": "fx:Thing"},
            "deep": {"attribute": "fx:deep"},
        }),
        _rule("O-01", "fx:other", {
            "thing": {"entityType": "fx:Thing"},
            "unrelated": {"attribute": "fx:unrelated"},
        }),
    ],
}


def test_it_follows_derived_bindings_to_the_bottom():
    consulted = consulted_attributes(PACK, "fx:answer")
    assert "fx:direct" in consulted, "a rule's own attribute binding"
    assert "fx:deep" in consulted, "an attribute only a sub-conclusion's rule reads"
    assert "fx:middle" in consulted, "the sub-conclusion itself"
    assert "fx:answer" in consulted, "the decision attribute itself"


def test_another_decisions_inputs_are_not_this_decisions():
    # The whole point. `fx:unrelated` is excluded case-wide like anything else,
    # and no rule behind `fx:answer` reads it.
    assert "fx:unrelated" not in consulted_attributes(PACK, "fx:answer")
    assert "fx:unrelated" in consulted_attributes(PACK, "fx:other")


def test_unknown_is_not_the_empty_set():
    """`None` means "cannot tell", and callers must not treat it as "consults
    nothing" — that difference is the difference between showing a reader an
    exclusion they did not need and hiding one that shaped their answer."""
    assert consulted_attributes(None, "fx:answer") is None
    assert consulted_attributes(PACK, None) is None
    assert consulted_attributes("not a pack", "fx:answer") is None
    # An attribute no rule concludes is knowable and genuinely reaches nothing.
    assert consulted_attributes(PACK, "fx:absent") == {"fx:absent"}


def test_a_cycle_terminates():
    cyclic = {
        "pack": {"name": "cyclic", "version": "1.0.0"},
        "rules": [
            _rule("C-01", "fx:a", {"t": {"entityType": "fx:T"}, "s": {"derived": "fx:b"}}),
            _rule("C-02", "fx:b", {"t": {"entityType": "fx:T"}, "s": {"derived": "fx:a"}}),
        ],
    }
    assert consulted_attributes(cyclic, "fx:a") == {"fx:a", "fx:b"}
