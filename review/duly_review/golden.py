"""Human corrections auto-become golden regression cases (README roadmap, M3).

A resolved review item captures a complete correction arc: a machine fact
abstained, a human corrected it, and the decision now derives from the
corrected facts. :func:`resolved_item_to_golden_case` freezes that arc as a
golden case — the case's facts as-of post-correction plus a freshly
adjudicated receipt — written into ``golden/`` in the corpus's exact layout
(``cases/<id>/case.yaml`` + ``cases/<id>/facts/*.json`` +
``receipts/<id>.json``), so ``python -m duly_assurance verify`` replays it
byte-for-byte forever after.

Case id series: review-born cases are ``review-NNNN`` — a distinct series so
they are recognizable as human-review provenance and so the synthetic
generator can preserve them across regenerations (``duly_assurance.generate``
skips ``review-*`` when it resets the corpus; see golden/README.md).
``verify`` and ``impact`` need no special handling — they glob case
directories regardless of id shape.

Bitemporal framing: the golden case keeps the original receipt's
``asOf.effective`` (the world did not change) and takes the resolution's
``recorded_at`` as ``asOf.knowledge`` (what changed is what we know) — the
same-effective/later-knowledge pair is exactly the replay story the store
exists for.

Determinism: no wall clock; every timestamp comes from the queue's event log
or the facts themselves.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from duly_kernel.api import adjudicate
from duly_store.store import FactStore

from .queue import ReviewQueue, ReviewQueueError

__all__ = ["GoldenCaseError", "next_review_case_id", "resolved_item_to_golden_case"]

_REVIEW_ID_RE = re.compile(r"^review-(\d{4})$")


class GoldenCaseError(ReviewQueueError):
    """The resolved item cannot be frozen as a golden case."""


def next_review_case_id(golden_dir: str | Path) -> str:
    """The next free id in the review series (``review-0001``, ...), scanning
    both cases/ and receipts/ so a half-written corpus never collides."""
    golden = Path(golden_dir)
    taken = set()
    cases = golden / "cases"
    if cases.is_dir():
        taken.update(p.name for p in cases.iterdir())
    receipts = golden / "receipts"
    if receipts.is_dir():
        taken.update(p.stem for p in receipts.glob("*.json"))
    n = 1
    while True:
        candidate = f"review-{n:04d}"
        if candidate not in taken:
            return candidate
        n += 1


def _dump_json(doc: dict) -> str:
    # Matches duly_assurance.generate._dump_json byte-for-byte.
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def _check_resolved(receipt: dict, facts: list[dict], item: dict) -> None:
    """The correction must actually have resolved the abstention: the item's
    (entity, attribute) must be bindable in the re-adjudicated run.

    Two ways it can still be unresolved: a `conflict` entry on the pair
    (e.g. two live human assertions), or every live fact for the pair is
    excluded by the abstention policy. A persisting `low_confidence` entry
    alone is fine — in the outranking (non-superseding) flow the below-floor
    machine fact stays live and stays honestly excluded while the human
    correction binds.

    That last allowance was written for a flow the queue no longer produces:
    `ReviewQueue.resolve` requires a `low_confidence` resolution to supersede
    the fact it rules on ([spec/compatibility.md](../../spec/compatibility.md)
    C6), so the state is unreachable *through the queue*. It stays permissive
    anyway. This function is handed an item by a caller it does not control —
    including, in a deployment, items resolved before that rule existed — and
    hardening a converter against a state its caller already prevents adds a
    second place for the invariant to be stated, and therefore a second place
    for it to be stated wrong.
    """
    key = (item["entity"], item["attribute"])
    entries = [
        a for a in receipt["abstentions"]
        if (a.get("entity"), a.get("attribute")) == key
    ]
    if any(a["reason"] == "conflict" for a in entries):
        raise GoldenCaseError(
            f"re-adjudication reports a conflict on {item['attribute']!r} for "
            f"{item['entity']!r} — the correction did not resolve the abstention"
        )
    excluded = {fid for a in entries for fid in a.get("facts") or []}
    bindable = [
        f for f in facts
        if f["entity"]["id"] == item["entity"]
        and f["attribute"] == item["attribute"]
        and f["id"] not in excluded
    ]
    if not bindable:
        raise GoldenCaseError(
            f"re-adjudication still abstains on {item['attribute']!r} for "
            f"{item['entity']!r} — the correction did not resolve the abstention"
        )


def resolved_item_to_golden_case(
    queue: ReviewQueue,
    store: FactStore,
    item_id: str,
    *,
    pack_path: str,
    golden_dir: str | Path,
    repo_root: str | Path | None = None,
    case_id: str | None = None,
) -> dict:
    """Convert a resolved review item into a committed golden case.

    - ``pack_path`` is the repo-relative path recorded in ``case.yaml``
      (receipts pin the pack's name+version, not its file location, so the
      path must be supplied by the caller, exactly as the generator's
      templates supply it).
    - ``store`` must hold the case's facts — the store is the system of
      record, and the golden case's fact set is its as-of projection at the
      resolution's knowledge time (which includes the ingested correction
      and excludes anything it superseded).
    - ``case_id`` defaults to the next free ``review-NNNN``.

    Refuses (GoldenCaseError) when the item is not resolved, when the store
    has no facts for the case, when re-adjudication still abstains on the
    item's attribute (the correction did not actually resolve it), or when
    two facts would collide on the corpus's attribute-derived file names.

    Returns ``{"caseId", "caseDir", "receiptPath", "receipt"}``.
    """
    item = queue.item(item_id)
    if item["status"] != "resolved":
        raise GoldenCaseError(
            f"only resolved items become golden cases; item is {item['status']!r}"
        )
    original_receipt = queue.opened_receipt(item_id)
    resolved_at = item["closedAt"]
    as_of_effective = original_receipt["asOf"]["effective"]
    question = original_receipt["decision"]["attribute"]

    facts = store.as_of(item["caseId"], knowledge=resolved_at)
    if not facts:
        raise GoldenCaseError(
            f"the fact store holds no facts for case {item['caseId']!r} as of "
            f"{resolved_at} — golden cases are projections of the store, so ingest "
            "the case's facts first"
        )

    # The base `pack_path` is relative to. Defaults to the *caller's* working
    # directory, which is what "repo-relative" means to whoever typed the path.
    # It used to default to `parents[2]` — duly's own install location — which
    # is the repository only when duly is running from a checkout, and is a
    # directory inside site-packages otherwise (M5 plan, A8).
    root = Path(repo_root) if repo_root is not None else Path.cwd()
    pack_file = root / pack_path
    if not pack_file.is_file():
        raise GoldenCaseError(f"pack not found at {pack_file} (pack_path must be repo-relative)")
    pack = yaml.safe_load(pack_file.read_text(encoding="utf-8"))

    receipt = adjudicate(facts, pack, as_of_effective, resolved_at, question)
    _check_resolved(receipt, facts, item)

    names = [f["attribute"].replace(":", "-") + ".json" for f in facts]
    if len(set(names)) != len(names):
        raise GoldenCaseError(
            "two facts map to the same attribute-derived file name; the corpus "
            "layout assumes one live fact per attribute (rule-IR v0)"
        )

    golden = Path(golden_dir)
    cid = case_id if case_id is not None else next_review_case_id(golden)
    case_dir = golden / "cases" / cid
    if case_dir.exists() or (golden / "receipts" / f"{cid}.json").exists():
        raise GoldenCaseError(f"golden case {cid!r} already exists")

    # Layout and formats match duly_assurance.generate._write_case exactly.
    (case_dir / "facts").mkdir(parents=True)
    case_yaml = (
        f"id: {cid}\n"
        f"pack: {pack_path}\n"
        f"question: {question}\n"
        f"asOfEffective: \"{as_of_effective}\"\n"
        f"asOfKnowledge: \"{resolved_at}\"\n"
    )
    (case_dir / "case.yaml").write_text(case_yaml, encoding="utf-8")
    for fact, name in zip(facts, names):
        (case_dir / "facts" / name).write_text(_dump_json(fact), encoding="utf-8")
    receipts_dir = golden / "receipts"
    receipts_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = receipts_dir / f"{cid}.json"
    receipt_path.write_text(_dump_json(receipt), encoding="utf-8")

    return {
        "caseId": cid,
        "caseDir": str(case_dir),
        "receiptPath": str(receipt_path),
        "receipt": receipt,
    }
