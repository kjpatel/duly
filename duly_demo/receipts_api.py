"""Receipt viewer — open a receipt you already have, and check whether it holds.

The decision workspace answers *what did the rules decide about this document*
by running an adjudication in front of you. That leaves a gap this module
fills: a receipt that already exists — one of the 351 in `golden/`, or one an
adopter's pipeline emitted last Tuesday — had no way to be read except `cat`.

Three stances hold this file together.

**Verification is part of the view, not a button next to it.** A viewer that
only formats is a JSON pretty-printer with better typography. Opening a
receipt here runs three checks and reports each one: the receipt's own hash
recomputed from its canonical bytes, the content hash of every fact it
pinned, and — where the facts and pack can be resolved — a full re-adjudication
through `duly_kernel.api.adjudicate` compared byte-for-byte. That is
`duly_assurance verify` narrowed to one receipt, which is the claim the
product makes, made checkable by someone holding a receipt and nothing else.

**The report is the kernel's, rendered in a third medium.** Sections come
from `duly_kernel.report.render_report_blocks` — the same `_build_sections`
the Markdown and the PDF walk. Never a second report implementation, for the
same reason the Rule Studio never writes a second expression parser: two
renderers that drift are two different accounts of one decision.

**Documents arrive as text and are parsed exactly once.** `/inspect` takes
raw JSON strings rather than objects, because a content hash is over bytes
and the browser's JSON is lossy where it matters — JavaScript has one number
type, so a fact's `"score": 1.0` comes back as `1` and hashes differently.
See `_parse_documents`.

**What cannot be resolved is said, not guessed.** A receipt pins its facts by
hash, not by value, and names its pack by name and version — so a receipt
arriving on its own is genuinely missing the quoted evidence and the rule
text, and the view says so rather than rendering a thinner report that looks
complete. The sharp case is a pack whose *version has moved* since the
receipt was written: the file at `rulepacks/<name>/pack.yaml` would render
rule descriptions that the receipt's rules never carried. That is refused —
`pack-moved` is reported as its own outcome, because a plausible-looking
misattribution is worse than a gap.

The same shape governs semantics. Replay is scoped to a semantics version
([spec/compatibility.md](../spec/compatibility.md) C3), so a receipt claiming
an `engine.version` this kernel does not implement gets its refusal before the
inputs are even gathered: re-adjudicating it here would answer a question
about *these* semantics and report it as though it were about the receipt's.

Deliberately not here: this module never writes. It reads `golden/` and
`rulepacks/` and holds uploaded receipts in the request that carried them.
"""

from __future__ import annotations

import importlib
import json
import re
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from .content import CONTENT

GOLDEN_DIR = CONTENT.golden
RULEPACKS_DIR = CONTENT.rulepacks

router = APIRouter(prefix="/api/receipts")

# A receipt's id is its hash, spelled as a URN. Both are checked: a receipt
# whose id disagrees with its own recomputed hash is not a receipt that would
# survive being looked up by id.
RECEIPT_URN_PREFIX = "urn:duly:receipt:sha256:"
FACT_URN_PREFIX = "urn:duly:fact:sha256:"

# A pack directory name, which is also what `pack.name` is in every committed
# pack. Receipts arrive from outside, so the name they carry is caller data.
_PACK_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")


# ---------------------------------------------------------------------------
# The kernel, reached lazily
# ---------------------------------------------------------------------------
#
# Every kernel reach in duly_demo/app.py is lazy on purpose: the demo has to start
# when duly_kernel is not importable and say so, rather than 500 on the one
# question it cannot answer. A module-scope import here would break that for
# all four pages at once, since app.py includes this router unconditionally —
# so this module reaches for the kernel the same way, and the checks below
# report "not checked" instead of raising.

_KERNEL_ENTRY_POINTS = {
    "adjudicate": ("duly_kernel.api", "adjudicate"),
    "content_hash": ("duly_kernel.receipt", "content_hash"),
    "render_report_blocks": ("duly_kernel.report", "render_report_blocks"),
    "check_replayable": ("duly_kernel.semantics", "check_replayable"),
    "UnsupportedSemantics": ("duly_kernel.semantics", "UnsupportedSemantics"),
}

KERNEL_UNAVAILABLE = "the kernel is unavailable (duly_kernel is not importable)"


def _kernel(name: str) -> Any:
    """One kernel entry point, or None when the kernel is not importable.

    Resolved per call rather than cached: `sys.modules` makes the success path
    a dict lookup, and the failure path stays retryable, so a kernel that
    appears while the demo is running is picked up — the same behaviour
    ``duly_demo/app.py._run_kernel`` goes out of its way to keep.
    """
    module, attribute = _KERNEL_ENTRY_POINTS[name]
    try:
        return getattr(importlib.import_module(module), attribute)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Corpus index
# ---------------------------------------------------------------------------
#
# Built once per process from the committed corpus. The corpus is immutable
# between commits, so a cache here is not a staleness risk the way a pack
# cache would be — and the alternative is re-reading 351 receipts per request.

_INDEX: list[dict[str, Any]] | None = None


def reset_index() -> None:
    """Drop the cached corpus index (tests call this after touching golden/)."""
    global _INDEX
    _INDEX = None


def _decision_summary(receipt: dict) -> str:
    """The decision's value, rendered plainly for a list row."""
    value = (receipt.get("decision") or {}).get("value") or {}
    kind = value.get("kind")
    if kind == "boolean":
        return "true" if value.get("value") else "false"
    if kind == "money":
        return f"{value.get('amount')} {value.get('currency')}"
    return str(value.get("value"))


def _short_attr(curie: str) -> str:
    i = curie.find(":")
    return curie[i + 1:] if i >= 0 else curie


def _build_index() -> list[dict[str, Any]]:
    receipts_dir = GOLDEN_DIR / "receipts"
    if not receipts_dir.is_dir():
        return []
    rows = []
    for path in sorted(receipts_dir.glob("*.json")):
        try:
            receipt = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        pack = receipt.get("rulePack") or {}
        decision = receipt.get("decision") or {}
        rows.append(
            {
                "caseId": path.stem,
                "pack": pack.get("name", ""),
                "packVersion": pack.get("version", ""),
                "attribute": decision.get("attribute", ""),
                "attributeShort": _short_attr(decision.get("attribute", "")),
                "value": _decision_summary(receipt),
                "effective": (receipt.get("asOf") or {}).get("effective", "")[:10],
                "receiptSha256": receipt.get("receiptSha256", ""),
                "abstentions": len(receipt.get("abstentions") or []),
            }
        )
    return rows


def _index() -> list[dict[str, Any]]:
    global _INDEX
    if _INDEX is None:
        _INDEX = _build_index()
    return _INDEX


# ---------------------------------------------------------------------------
# Resolution: what a receipt can be shown alongside
# ---------------------------------------------------------------------------
#
# A receipt is self-describing about its *decision* and self-verifying about
# its *hash*, but it pins facts by hash and names its pack by name+version.
# So the report has two tiers, and which one you got is part of the answer.


def _packs_named(name: str) -> list[tuple[Path, dict]]:
    """Every pack under the content root that *declares* this `pack.name`.

    Discovery, not path construction — and the distinction is the whole
    function. `rulepacks/<directory>/pack.yaml` and the `pack.name` inside that
    file are two different strings, and nothing in this repository requires
    them to match: not the kernel, not the receipt (which records the declared
    name and never the path), not the pack schema. Only duly's own six packs
    happen to agree, which is exactly the condition under which an assumption
    survives every test.

    Resolving by joining the receipt's name into a path therefore answered
    "unavailable" for any adopter whose directory is named anything else —
    silently, as `replay: unavailable`, which reads like a missing pack rather
    than like a lookup that was never going to succeed. Reading each pack's own
    declaration is the same discovery the rule studio does (`_known_slugs`) and
    costs a handful of small YAML parses per request.

    Not cached, deliberately: `_INDEX` above caches an immutable corpus, but a
    pack file is the one thing here someone edits mid-session.
    """
    found: list[tuple[Path, dict]] = []
    if not RULEPACKS_DIR.is_dir():
        return found
    for path in sorted(RULEPACKS_DIR.glob("*/pack.yaml")):
        try:
            pack = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue  # an unreadable neighbour is not this receipt's problem
        if not isinstance(pack, dict):
            continue
        if str(((pack.get("pack") or {}).get("name") or "")) == name:
            found.append((path, pack))
    return found


def _resolve_pack(receipt: dict) -> tuple[dict | None, dict[str, Any]]:
    """The pack this receipt was produced by, if the working tree still has
    that exact version.

    Returns (pack_or_None, status). A pack file whose version has moved past
    the receipt's is NOT returned: rendering rule descriptions out of it would
    attribute text to rules that never carried it.
    """
    ref = receipt.get("rulePack") or {}
    name, version = ref.get("name"), ref.get("version")
    if not name:
        return None, {"state": "unavailable", "reason": "receipt names no rule pack"}

    # `name` is caller data — a pasted receipt can carry anything. Nothing below
    # joins it into a path any more, so this is no longer the traversal guard it
    # once was; it stays because a string that cannot be a pack name cannot name
    # a pack, and saying so is a better answer than an empty search. Keeping it
    # also keeps the invariant cheap to re-check if a future caller does build a
    # path from this value.
    if not _PACK_NAME.fullmatch(str(name)):
        return None, {
            "state": "unavailable",
            "reason": f"{name!r} is not a rule-pack name, so no pack was looked up",
        }

    candidates = _packs_named(str(name))
    if not candidates:
        return None, {
            "state": "unavailable",
            "reason": f"no pack named {name!r} under rulepacks/",
        }

    for path, pack in candidates:
        on_disk = str(((pack.get("pack") or {}).get("version", "")))
        if on_disk == str(version):
            return pack, {
                "state": "resolved",
                "source": f"rulepacks/{path.parent.name}/pack.yaml",
                "version": on_disk,
            }

    # Named, but at no version this receipt was produced by. Report every
    # version carrying the name rather than the first: two directories can
    # declare one pack at two versions, and naming only one of them would make
    # the answer depend on directory order.
    path, pack = candidates[0]
    on_disk = ", ".join(
        str(((p.get("pack") or {}).get("version", ""))) for _, p in candidates
    )
    return None, {
        "state": "moved",
        "reason": (
            f"rulepacks/{path.parent.name}/pack.yaml is now v{on_disk}; this "
            f"receipt was produced by v{version}. Rule text is not shown from "
            f"a different version."
        ),
        "receiptVersion": str(version),
        "workingTreeVersion": on_disk,
    }


def _resolve_golden_facts(case_id: str) -> tuple[list[dict], dict[str, Any]]:
    facts_dir = GOLDEN_DIR / "cases" / case_id / "facts"
    if not facts_dir.is_dir():
        return [], {"state": "unavailable", "reason": f"no facts for case {case_id}"}
    facts = []
    for path in sorted(facts_dir.glob("*.json")):
        try:
            facts.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError) as exc:
            return [], {"state": "unavailable", "reason": f"{path.name}: {exc}"}
    return facts, {
        "state": "resolved",
        "source": f"golden/cases/{case_id}/facts",
        "count": len(facts),
    }


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------
#
# Three checks, reported separately, because they fail for different reasons
# and a caller needs to tell them apart. The hash check needs nothing but the
# receipt; the fact check needs the facts; replay needs both plus the pack.


def _check_receipt_hash(receipt: dict) -> dict[str, Any]:
    claimed = receipt.get("receiptSha256")
    if not isinstance(claimed, str) or not claimed:
        return {
            "id": "receiptHash",
            "label": "Receipt hash",
            "state": "fail",
            "detail": "receipt carries no receiptSha256 field.",
        }
    content_hash = _kernel("content_hash")
    if content_hash is None:
        return {
            "id": "receiptHash",
            "label": "Receipt hash",
            "state": "unavailable",
            "detail": (
                f"the canonical body cannot be re-hashed here because "
                f"{KERNEL_UNAVAILABLE}."
            ),
        }
    recomputed = content_hash(receipt, "receiptSha256")
    if recomputed != claimed:
        return {
            "id": "receiptHash",
            "label": "Receipt hash",
            "state": "fail",
            "detail": (
                "recomputed SHA-256 of the canonical body does not match the "
                "receipt's own receiptSha256 — this document has been altered "
                "since it was emitted."
            ),
            "expected": claimed,
            "actual": recomputed,
        }
    claimed_id = receipt.get("id")
    if claimed_id != f"{RECEIPT_URN_PREFIX}{claimed}":
        return {
            "id": "receiptHash",
            "label": "Receipt hash",
            "state": "fail",
            "detail": (
                f"hash matches, but the receipt id is {claimed_id!r} rather "
                f"than {RECEIPT_URN_PREFIX}{claimed!r}."
            ),
        }
    return {
        "id": "receiptHash",
        "label": "Receipt hash",
        "state": "pass",
        "detail": (
            "SHA-256 of the canonical JSON body (sorted keys, minimal "
            "separators, id and receiptSha256 excluded) matches the hash the "
            "receipt carries."
        ),
    }


def _check_facts(receipt: dict, facts: list[dict], facts_status: dict) -> dict:
    pinned = [
        p.get("id") for p in receipt.get("inputFacts") or [] if isinstance(p, dict)
    ]
    if not pinned:
        return {
            "id": "facts",
            "label": "Input facts",
            "state": "pass",
            "detail": (
                "this receipt pins no input facts — the decision rests on the "
                "pack's default presumption alone, with nothing to re-hash."
            ),
        }
    if facts_status.get("state") != "resolved":
        return {
            "id": "facts",
            "label": "Input facts",
            "state": "unavailable",
            "detail": (
                f"{len(pinned)} facts are pinned by hash, but their bodies were "
                f"not supplied: {facts_status.get('reason', 'no facts available')}. "
                "A receipt pins facts by content hash, so it cannot reproduce "
                "them on its own — and the viewer resolves bodies from disk "
                "only for the committed corpus, so a receipt from a live "
                "session must arrive with its facts. Paste them alongside it "
                "and this check runs."
            ),
        }
    content_hash = _kernel("content_hash")
    if content_hash is None:
        return {
            "id": "facts",
            "label": "Input facts",
            "state": "unavailable",
            "detail": (
                f"the supplied facts cannot be re-hashed here because "
                f"{KERNEL_UNAVAILABLE}."
            ),
        }

    by_id = {f.get("id"): f for f in facts if isinstance(f, dict)}
    missing = [fid for fid in pinned if fid not in by_id]
    if missing:
        return {
            "id": "facts",
            "label": "Input facts",
            "state": "fail",
            "detail": (
                f"{len(missing)} of {len(pinned)} pinned facts are absent from "
                "the supplied fact set."
            ),
            "missing": missing,
        }
    tampered = []
    for fid in pinned:
        fact = by_id[fid]
        recomputed = content_hash(fact, "contentHash")
        if recomputed != fact.get("contentHash") or fid != f"{FACT_URN_PREFIX}{recomputed}":
            tampered.append(fid)
    if tampered:
        return {
            "id": "facts",
            "label": "Input facts",
            "state": "fail",
            "detail": (
                f"{len(tampered)} of {len(pinned)} facts do not hash to the id "
                "they carry — the evidence has been altered."
            ),
            "tampered": tampered,
        }
    return {
        "id": "facts",
        "label": "Input facts",
        "state": "pass",
        "detail": (
            f"all {len(pinned)} pinned facts are present and each one hashes to "
            "the content hash in its own id."
        ),
    }


def _check_replay(
    receipt: dict,
    facts: list[dict],
    pack: dict | None,
    facts_status: dict,
    pack_status: dict,
) -> dict:
    # Semantics first, because it is the one refusal that is not about missing
    # inputs. Replay is scoped to a semantics version (spec/compatibility.md
    # C3): this kernel is not entitled to an opinion about a receipt sealed
    # under semantics it does not implement, and a coincidental pass on the
    # cases where two semantics agree would be worse than no answer.
    check_replayable = _kernel("check_replayable")
    unsupported = _kernel("UnsupportedSemantics") or ()
    if check_replayable is not None:
        try:
            check_replayable(receipt)
        except unsupported as exc:
            return {
                "id": "replay",
                "label": "Replay",
                "state": "unavailable",
                "detail": str(exc),
            }

    if pack_status.get("state") == "moved":
        return {
            "id": "replay",
            "label": "Replay",
            "state": "unavailable",
            "detail": (
                f"{pack_status['reason']} Replaying against a different pack "
                "version would answer a different question."
            ),
        }
    if pack is None or facts_status.get("state") != "resolved":
        missing = []
        if facts_status.get("state") != "resolved":
            missing.append("the input facts")
        if pack is None:
            missing.append("the rule pack")
        return {
            "id": "replay",
            "label": "Replay",
            "state": "unavailable",
            "detail": (
                f"re-adjudication needs {' and '.join(missing)}, which could not "
                "be resolved. Supply them to check that this receipt reproduces."
            ),
        }

    as_of = receipt.get("asOf") or {}
    attribute = (receipt.get("decision") or {}).get("attribute")
    if not attribute or not as_of.get("effective") or not as_of.get("knowledge"):
        return {
            "id": "replay",
            "label": "Replay",
            "state": "unavailable",
            "detail": "receipt is missing the decision attribute or its asOf pair.",
        }
    adjudicate = _kernel("adjudicate")
    if adjudicate is None:
        return {
            "id": "replay",
            "label": "Replay",
            "state": "unavailable",
            "detail": (
                f"the receipt cannot be re-adjudicated here because "
                f"{KERNEL_UNAVAILABLE}."
            ),
        }

    try:
        recomputed = adjudicate(
            facts,
            pack,
            str(as_of["effective"]),
            str(as_of["knowledge"]),
            str(attribute),
        )
    except Exception as exc:  # noqa: BLE001 — any failure is a replay failure
        return {
            "id": "replay",
            "label": "Replay",
            "state": "fail",
            "detail": f"re-adjudication raised {type(exc).__name__}: {exc}",
        }

    if recomputed.get("receiptSha256") != receipt.get("receiptSha256"):
        differing = sorted(
            k
            for k in set(recomputed) | set(receipt)
            if recomputed.get(k) != receipt.get(k)
        )
        return {
            "id": "replay",
            "label": "Replay",
            "state": "fail",
            "detail": (
                "re-running the kernel over these facts, this pack version and "
                "this asOf pair produced a different receipt. Differing fields: "
                f"{', '.join(differing)}."
            ),
            "expected": receipt.get("receiptSha256"),
            "actual": recomputed.get("receiptSha256"),
        }
    return {
        "id": "replay",
        "label": "Replay",
        "state": "pass",
        "detail": (
            "re-running the kernel over the pinned facts, the named pack "
            "version and the receipt's own asOf pair reproduced this receipt "
            "byte-for-byte."
        ),
    }


def _verify(
    receipt: dict,
    facts: list[dict],
    pack: dict | None,
    facts_status: dict,
    pack_status: dict,
) -> dict[str, Any]:
    checks = [
        _check_receipt_hash(receipt),
        _check_facts(receipt, facts, facts_status),
        _check_replay(receipt, facts, pack, facts_status, pack_status),
    ]
    states = {c["state"] for c in checks}
    if "fail" in states:
        verdict, headline = "fail", "This receipt does not hold."
    elif "unavailable" in states:
        # The hash check is the one that needs nothing but the receipt, so it
        # going unavailable means the *deployment* is short a kernel, not that
        # the caller is short an input. Saying "the inputs you supplied" there
        # would blame the reader for the server's gap.
        verdict, headline = (
            "partial",
            "Nothing here can be checked without the kernel."
            if checks[0]["state"] == "unavailable"
            else (
                'Verified as far as the supplied inputs allow. "Not checked" '
                "is a missing input, not a failed check — supply what each "
                "card names and it runs."
            ),
        )
    else:
        verdict, headline = "pass", "This receipt replays byte-for-byte."
    return {"verdict": verdict, "headline": headline, "checks": checks}


# ---------------------------------------------------------------------------
# The view
# ---------------------------------------------------------------------------


def _view(
    receipt: dict, facts: list[dict], facts_status: dict, case_id: str | None
) -> dict[str, Any]:
    """Assemble everything the viewer shows for one receipt."""
    pack, pack_status = _resolve_pack(receipt)
    resolution = (
        "resolved"
        if pack is not None and facts_status.get("state") == "resolved"
        else "partial"
    )
    # No kernel means no report sections. An empty list is the honest answer:
    # the verification pane below already names the kernel as the reason every
    # check came back "not checked".
    render_report_blocks = _kernel("render_report_blocks")
    return {
        "caseId": case_id,
        "receipt": receipt,
        "report": [] if render_report_blocks is None else render_report_blocks(receipt, facts, pack),
        "resolution": {
            "state": resolution,
            "facts": facts_status,
            "pack": pack_status,
        },
        "verification": _verify(receipt, facts, pack, facts_status, pack_status),
    }


def _golden_receipt(case_id: str) -> dict:
    if "/" in case_id or "\\" in case_id or case_id.startswith("."):
        raise HTTPException(status_code=404, detail=f"Unknown case: {case_id}")
    path = GOLDEN_DIR / "receipts" / f"{case_id}.json"
    if not path.is_file():
        raise HTTPException(
            status_code=404, detail=f"No golden receipt for case {case_id}"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _golden_view(case_id: str) -> dict[str, Any]:
    receipt = _golden_receipt(case_id)
    facts, facts_status = _resolve_golden_facts(case_id)
    return _view(receipt, facts, facts_status, case_id)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/corpus")
def corpus() -> dict[str, Any]:
    """The golden corpus as a browsable index."""
    rows = _index()
    packs = sorted({r["pack"] for r in rows if r["pack"]})
    return {
        "cases": rows,
        "packs": packs,
        "count": len(rows),
        "note": (
            "The committed golden corpus: every case duly replays on each push. "
            "Opening one re-verifies it here."
        ),
    }


@router.get("/corpus/{case_id}")
def corpus_case(case_id: str) -> dict[str, Any]:
    return _golden_view(case_id)


# There is deliberately no lookup-by-hash route. `/corpus` already carries
# every case's receiptSha256, so resolving a hash to a case is something the
# caller can do with the index it has already loaded — a second route would
# be a second way to ask one question. The server does the same lookup inline
# in `inspect`, where it is not redundant: a pasted receipt cannot tell the
# client whether the corpus holds its facts.


class InspectRequest(BaseModel):
    documents: list[str]


def _parse_documents(blobs: list[str]) -> list[dict]:
    """Parse raw JSON text into documents, preserving numeric fidelity.

    THIS TAKES TEXT, NOT OBJECTS, AND THAT IS THE WHOLE POINT. A content hash
    is over bytes, and a document that has been through a *second* language's
    JSON parser is not the same bytes. JavaScript has one number type: it
    reads the `"score": 1.0` in a grounded fact and writes back `"score": 1`,
    which is a different canonical body and therefore a different content
    hash. A browser that parsed a receipt and re-serialized it would be
    verifying a document nobody ever emitted, and would report every fact as
    tampered with — which is exactly what this endpoint did before it took
    text.

    So the caller sends the bytes it was given and Python does the only
    parse. Python's json round-trips 1.0 as a float, so the canonical form
    survives.
    """
    docs: list[dict] = []
    for i, blob in enumerate(blobs):
        text = (blob or "").strip()
        if not text:
            continue
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Document {i + 1} is not valid JSON: {exc}",
            )
        items = parsed if isinstance(parsed, list) else [parsed]
        docs.extend(item for item in items if isinstance(item, dict))
    return docs


@router.post("/inspect")
def inspect(req: InspectRequest) -> dict[str, Any]:
    """View and verify a receipt supplied by the caller.

    `documents` is a list of raw JSON text blobs — each one an object or an
    array of them — and they are sorted here by what they carry: a receipt
    has `receiptSha256`, a grounded fact has `contentHash`. Sorting them
    server-side means the caller never has to re-serialize anything to put a
    document in the right field (see `_parse_documents` for why that would be
    fatal).

    Facts are optional, and supplying them is what promotes the view from
    receipt-only to resolved: without them the quoted evidence and the replay
    check are reported unavailable rather than skipped.
    """
    docs = _parse_documents(req.documents)
    receipts = [d for d in docs if "receiptSha256" in d]
    if not receipts:
        raise HTTPException(
            status_code=422,
            detail=(
                "No DecisionReceipt among those documents: none carries a "
                "receiptSha256. A receipt has decision, rulePack, derivation "
                "and receiptSha256."
            ),
        )
    receipt = receipts[0]
    if "decision" not in receipt:
        raise HTTPException(
            status_code=422,
            detail="That receipt has a receiptSha256 but no `decision` field.",
        )
    facts = [d for d in docs if "contentHash" in d and "receiptSha256" not in d]
    if facts:
        facts_status = {
            "state": "resolved",
            "source": "supplied with the receipt",
            "count": len(facts),
        }
    else:
        facts_status = {
            "state": "unavailable",
            "reason": "no facts were supplied alongside the receipt",
        }

    # A pasted receipt that *is* a corpus receipt is worth saying so: it means
    # the facts are on disk, and the viewer can resolve what the paste could not.
    sha = receipt.get("receiptSha256")
    known = next((r for r in _index() if r["receiptSha256"] == sha), None) if sha else None
    if known and not facts:
        golden_facts, golden_status = _resolve_golden_facts(known["caseId"])
        if golden_status.get("state") == "resolved":
            facts, facts_status = golden_facts, golden_status

    view = _view(receipt, facts, facts_status, known["caseId"] if known else None)
    view["knownCase"] = known["caseId"] if known else None
    return view


@router.get("/corpus/{case_id}/receipt.json")
def download_receipt(case_id: str) -> Response:
    receipt = _golden_receipt(case_id)
    return Response(
        content=json.dumps(receipt, indent=2, ensure_ascii=False),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{case_id}-receipt.json"'
        },
    )


@router.get("/corpus/{case_id}/bundle.json")
def download_bundle(case_id: str) -> Response:
    """The receipt and the facts it was adjudicated over, in one file.

    The bare receipt is the artifact whose hash is its identity; this is the
    artifact that still verifies when nobody has the facts on disk. Both are
    offered because the difference is a disclosure decision, not a convenience
    one: fact bodies carry the source quotes, so the receipt alone proves what
    was decided without showing the evidence it was decided from.

    The shape is a JSON array of documents, verbatim — `/inspect` already
    sorts receipts from facts by the fields they carry, so a bundle uploads as
    one file and verifies whole. It wraps rather than edits for the usual
    reason: a key added to a hashed body changes the hash.
    """
    receipt = _golden_receipt(case_id)
    facts, status = _resolve_golden_facts(case_id)
    if status.get("state") != "resolved":
        raise HTTPException(
            status_code=404,
            detail=(
                f"No bundle for case {case_id}: its facts could not be "
                f"resolved ({status.get('reason', 'unknown reason')}). The "
                "receipt alone is still available."
            ),
        )
    return Response(
        content=json.dumps([receipt, *facts], indent=2, ensure_ascii=False),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{case_id}-bundle.json"'
        },
    )


@router.get("/corpus/{case_id}/report")
def download_report(case_id: str, format: str = "md") -> Response:
    """The audit report for a corpus receipt, as Markdown or PDF.

    Same renderers the decision workspace's export uses — this route differs
    only in resolving its inputs from `golden/` instead of a live scenario.
    """
    if format not in ("md", "pdf"):
        raise HTTPException(
            status_code=422, detail=f"format must be 'md' or 'pdf', got {format!r}"
        )
    receipt = _golden_receipt(case_id)
    facts, _status = _resolve_golden_facts(case_id)
    pack, _pack_status = _resolve_pack(receipt)

    try:
        from duly_kernel.report import (  # noqa: PLC0415
            render_report_markdown,
            render_report_pdf,
        )
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Report renderer unavailable (duly_kernel.report not importable).",
        )

    if format == "md":
        content: bytes = render_report_markdown(receipt, facts, pack).encode("utf-8")
        media_type = "text/markdown; charset=utf-8"
    else:
        try:
            content = render_report_pdf(receipt, facts, pack)
        except ImportError:
            raise HTTPException(
                status_code=503,
                detail="PDF rendering needs reportlab, which is not installed.",
            )
        media_type = "application/pdf"
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{case_id}-audit.{format}"'
        },
    )
