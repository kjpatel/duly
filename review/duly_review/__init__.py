"""duly review queue: abstention routing, human corrections re-entering the
store as first-class facts, calibration label export, and correction arcs
frozen as golden regression cases.

The queue closes the loop the architecture promises: the kernel converts
confident wrongness into explicit abstention (receipt ``abstentions``,
optionally routed via the pack's ``abstentionPolicy.routeTo``); this package
turns those entries into reviewable items; a human resolution ingests a
human-asserted GroundedFact through the fact store's public API (where the
conflict policy and ``supersedes`` chains already give it precedence); and
resolved items yield the labeled ``(raw_score, correct)`` pairs the
calibration module was built to consume — with the censored-sample caveat
documented on ``calibration_pairs``.
"""

from .golden import GoldenCaseError, next_review_case_id, resolved_item_to_golden_case
from .queue import (
    ITEM_URN_PREFIX,
    InvalidCorrectionError,
    InvalidTransitionError,
    ReviewQueue,
    ReviewQueueError,
    UnknownItemError,
    calibration_pairs,
    enqueue_receipt,
    item_natural_key,
    values_equal,
)

__all__ = [
    "ReviewQueue",
    "ReviewQueueError",
    "UnknownItemError",
    "InvalidTransitionError",
    "InvalidCorrectionError",
    "GoldenCaseError",
    "enqueue_receipt",
    "calibration_pairs",
    "values_equal",
    "item_natural_key",
    "ITEM_URN_PREFIX",
    "next_review_case_id",
    "resolved_item_to_golden_case",
]
