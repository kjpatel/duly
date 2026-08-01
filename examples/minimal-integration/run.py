#!/usr/bin/env python3
"""duly, consumed from outside: three facts, three rules, one receipt.

Run it:

    python run.py

This is the whole integration — every line an adopting team would have to
write, and nothing else. It is deliberately not a duly test: it imports the
toolkit the way a wheel installed from PyPI exposes it, keeps its ontology
and its rule pack in its own directory, and never reaches into duly's
repository for anything. `check_wheel.sh` beside it proves that by running
this file against an installed wheel with the source tree off `sys.path`.

The five steps below are the whole contract. If your integration does these
five things, the receipt it produces is replayable by anyone holding it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

from duly_conformance import OntologyRegistry, assert_conformant, parse_ontology
from duly_kernel.api import adjudicate
from duly_kernel.receipt import content_hash

HERE = Path(__file__).resolve().parent

CASE_ID = "acme-claim-4471"
CLAIM = {"id": "claim:4471", "type": "ex:ExpenseClaim"}

# The bitemporal point this decision is evaluated at. Caller-supplied, never
# the wall clock: that is what makes the answer reproducible forever.
AS_OF_EFFECTIVE = "2026-03-02"
AS_OF_KNOWLEDGE = "2026-03-02T14:00:00Z"


def seal(fact: dict) -> dict:
    """Content-address a fact: hash its bytes, derive its id from the hash.

    Every artifact duly produces is identified by what it contains, so the
    id cannot disagree with the content. `content_hash` is duly's own — do
    not reimplement it, because the canonical form (sorted keys, minimal
    separators, `id` and the hash field excluded) is what every verifier
    everywhere will recompute.
    """
    digest = content_hash(fact, "contentHash")
    return {"id": f"urn:duly:fact:sha256:{digest}", "contentHash": digest, **fact}


def facts() -> list[dict]:
    """The three facts this decision consumes.

    A real integration builds these from an extraction adapter's output. The
    shape is the same either way, and it is the shape that matters: each fact
    is one entity-attribute-value assertion carrying where it came from, who
    asserted it, how confident they were, and when it was recorded.
    """
    common = {
        "caseId": CASE_ID,
        "entity": CLAIM,
        "recordedAt": "2026-03-01T09:15:00Z",
        "status": "asserted",
        "schemaRef": {"ontology": "acme-expense", "version": "1.0.0"},
    }
    # Grounding for the two facts read off the submitted receipt image. The
    # span points into a *rendition* — one extractor's reading of the bytes —
    # not into the PDF, because two extractors produce two different texts
    # from identical bytes and old spans must keep resolving.
    scan = {
        "kind": "document",
        "documentId": "acme:receipt:4471",
        "documentSha256": "5f2e" + "0" * 60,  # the receipt image's bytes
        "rendition": {
            "id": "acme:rendition:4471:v1",
            "extractor": "acme-ocr",
            "extractorVersion": "3.1.0",
        },
    }
    machine = {
        "kind": "machine",
        "at": "2026-03-01T09:15:00Z",
        "extractor": {"name": "acme-ocr", "version": "3.1.0"},
    }

    return [
        seal({
            **common,
            "attribute": "ex:amount",
            "value": {"kind": "money", "amount": "312.40", "currency": "USD"},
            "grounding": {**scan, "charSpan": {"start": 84, "end": 91}, "quote": "$312.40"},
            "assertion": machine,
            "confidence": {"score": 0.97, "method": "raw"},
        }),
        seal({
            **common,
            "attribute": "ex:category",
            "value": {
                "kind": "code",
                "value": "Travel",
                "codeSystem": "acme-expense/categories",
            },
            "grounding": {**scan, "charSpan": {"start": 12, "end": 18}, "quote": "Travel"},
            "assertion": machine,
            "confidence": {"score": 0.93, "method": "raw"},
        }),
        # No document says "nobody approved this" — absence is not a span. A
        # fact with no document behind it is grounded by attestation instead,
        # naming who says so and how it was established.
        seal({
            **common,
            "attribute": "ex:preApproved",
            "value": {"kind": "boolean", "value": False},
            "grounding": {
                "kind": "attestation",
                "actor": "acme:approvals-system",
                "channel": "approvals API query",
                "at": "2026-03-01T09:15:00Z",
                "note": "No approval record exists for claim 4471.",
            },
            "assertion": {
                "kind": "human",
                "at": "2026-03-01T09:15:00Z",
                "actor": {"id": "acme:approvals-system", "role": "system-of-record"},
            },
        }),
    ]


def main() -> int:
    # 1. Load your ontology. It is yours, it lives with your code, and duly
    #    resolves it from the registry you hand it — never from a path of
    #    duly's choosing.
    registry = OntologyRegistry(
        [parse_ontology(yaml.safe_load((HERE / "ontology/acme-expense/1.0.0.yaml").read_text()))]
    )

    # 2. Admit your facts. The gate holds each one to the ontology version it
    #    pins: entity type declared, attribute declared *on that class*, value
    #    kind matching the slot's range, code values inside the code system.
    #    A misspelled attribute fails loudly here instead of becoming a rule
    #    that silently never binds.
    claim_facts = facts()
    for fact in claim_facts:
        assert_conformant(fact, registry)

    # 3. Load your rule pack. `adjudicate` validates it; a malformed pack, an
    #    unprovable same-priority overlap, or an unknown phrasing placeholder
    #    is a load error, not a surprise at decision time.
    pack = yaml.safe_load((HERE / "expense-policy.pack.yaml").read_text())

    # 4. Decide. The as-of pair is yours to choose and is recorded on the
    #    receipt, so this exact question can be re-asked forever.
    receipt = adjudicate(
        claim_facts, pack, AS_OF_EFFECTIVE, AS_OF_KNOWLEDGE, "ex:reimbursable"
    )

    # 5. Verify what you were handed. This is the check anyone holding the
    #    receipt can run — recompute the hash over its canonical bytes and
    #    compare. It proves the document is unaltered since it was sealed; it
    #    does *not* prove the seal was honest. Only re-running the rules does
    #    that, which is what `duly_assurance verify` is for.
    recomputed = content_hash(receipt, "receiptSha256")
    if recomputed != receipt["receiptSha256"]:
        print("FAIL: receipt hash does not match its own bytes", file=sys.stderr)
        return 1

    fired = [r["ruleId"] for r in receipt["rulesFired"]]
    defeated = sorted({d for r in receipt["rulesFired"] for d in r.get("defeated", [])})

    print(f"case            {receipt['caseId']}")
    print(f"decision        ex:reimbursable = {receipt['decision']['value']['value']}")
    print(f"rules fired     {', '.join(fired)}")
    print(f"rules defeated  {', '.join(defeated) or '(none)'}")
    print(f"input facts     {len(receipt['inputFacts'])} pinned by content hash")
    print(f"receipt         {receipt['receiptSha256'][:16]}… (hash verified)")

    # What this example asserts, so it fails loudly rather than printing
    # something plausible: the claim is over the limit and unapproved, so the
    # exception must fire and must be recorded as defeating the presumption.
    assert receipt["decision"]["value"] == {"kind": "boolean", "value": False}
    assert "EXP-TRAVELCAP-01" in fired
    assert "EXP-DEFAULT-00" in defeated
    assert len(receipt["inputFacts"]) == 3

    (HERE / "receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )
    print("\nwrote receipt.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
