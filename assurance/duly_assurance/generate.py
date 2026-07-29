"""Golden-corpus generator: python -m duly_assurance generate.

Synthesizes adjudication cases from per-scenario templates, adjudicates each
with the reference kernel, and writes cases + receipts under the output
directory (golden/README.md is the authoritative contract).

Determinism contract:
- No wall-clock reads anywhere. Every timestamp is derived from the case's
  own synthetic dates.
- All randomness flows from `random.Random` streams seeded from --seed. Each
  template gets its own stream seeded from ``f"{seed}:{template_name}"`` so
  adding a template never disturbs another template's draws.
- Case ids are ``<id_prefix>-<counter:04d>`` (e.g. notice-ny-0001, trid-0001),
  assigned in draw order. Regeneration with the same seed and templates is
  byte-identical.

Redraw rule: if a drawn case raises AdjudicationError, that draw is invalid;
it is discarded and the next draw is taken from the *same* per-template RNG
stream while the case id stays fixed. Because the stream position only
depends on prior draws, the redraw is deterministic. Bounded at 20 attempts
per case id, after which generation aborts loudly.

Template registry: STATE_TEMPLATES is data, not code. Adding a state to the
notice scenario is a single registry line built by `notice_template()`, e.g.

    "fl": notice_template("US-FL", (5, 90)),

once the pack carries rules gated on that governingState.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import random
import shutil
import sys
from decimal import Decimal
from pathlib import Path

import yaml

from duly_kernel.api import adjudicate
from duly_kernel.engine import AdjudicationError

GENERATOR_NAME = "duly-golden-generator"
GENERATOR_VERSION = "0.1.0"

NOTICE_PACK = "rulepacks/termination-notice-us-states/pack.yaml"
TRID_PACK = "rulepacks/trid-fee-tolerance-us-federal/pack.yaml"

# Synthetic policy expiration dates span this window (2025-2026) so that
# mailed dates (= asOf.effective) land on both sides of the pack's
# 2026-01-01 rule-version boundary (NY-NR-45-LEGACY vs NY-NR-45).
EXPIRATION_START = _dt.date(2025, 6, 1)
EXPIRATION_END = _dt.date(2026, 12, 31)


def notice_template(
    state: str,
    margin_days: tuple[int, int],
    *,
    nonpayment_share: float = 0.2,
) -> dict:
    """Registry entry for one state's termination-notice scenario.

    `state` is the ISO 3166-2 governing-state code (e.g. "US-NY");
    `margin_days` is the inclusive (low, high) range of days between the
    notice mailing date and the policy expiration, drawn uniformly so cases
    cross the pack's compliance thresholds in both directions.
    """
    return {
        "kind": "notice",
        "id_prefix": f"notice-{state.rsplit('-', 1)[-1].lower()}",
        "pack": NOTICE_PACK,
        "question": "nc:noticeCompliant",
        "ontology": "duly-starter-notice",
        "state": state,
        "notice_type": "Nonrenewal",
        "margin_days": margin_days,
        "nonpayment_share": nonpayment_share,
        "weight": 3,
    }


# Template registry: adding a scenario variant is adding a data entry here,
# not code. Notice-state entries are one line each via notice_template().
STATE_TEMPLATES: dict[str, dict] = {
    "ny": notice_template("US-NY", (5, 90)),
    # Margin ranges cross each state's statutory threshold both ways
    # (NY 45, FL 120, CA 75 days).
    "fl": notice_template("US-FL", (30, 180)),
    "ca": notice_template("US-CA", (15, 140)),
    "trid": {
        "kind": "trid",
        "id_prefix": "trid",
        "pack": TRID_PACK,
        "question": "trid:toleranceCureAmount",
        "ontology": "duly-starter-trid",
        "as_of_effective": "2026-03-15",
        "weight": 1,
    },
}


# ---------------------------------------------------------------------------
# Canonicalization + content addressing (mirrors spec/validate.py)
# ---------------------------------------------------------------------------


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def content_hash(doc: dict, hash_field: str = "contentHash") -> str:
    body = {k: v for k, v in doc.items() if k not in ("id", hash_field)}
    return hashlib.sha256(canonical(body)).hexdigest()


# ---------------------------------------------------------------------------
# Fact construction
# ---------------------------------------------------------------------------


def make_fact(
    case_ref: str,
    entity_id: str,
    entity_type: str,
    attribute: str,
    value: dict,
    ontology: str,
    ts: str,
    *,
    confidence: dict | None = None,
) -> dict:
    """Build a schema-valid GroundedFact for the synthetic corpus.

    Grounding is an honest attestation (this corpus does not fake source
    documents); the assertion is a machine assertion by the generator; all
    timestamps are the derived per-case timestamp `ts` (no wall clock).
    `confidence` defaults to a fully-confident raw score; low-confidence
    templates pass an explicit score to exercise the pack abstention policy.
    """
    doc = {
        "caseId": case_ref,
        "entity": {"id": entity_id, "type": entity_type},
        "attribute": attribute,
        "value": value,
        "grounding": {
            "kind": "attestation",
            "actor": "golden-generator",
            "channel": "synthetic",
            "at": ts,
        },
        "assertion": {
            "kind": "machine",
            "at": ts,
            "extractor": {"name": GENERATOR_NAME, "version": GENERATOR_VERSION},
        },
        "confidence": confidence if confidence is not None else {"score": 1.0, "method": "raw"},
        "recordedAt": ts,
        "status": "asserted",
        "schemaRef": {"ontology": ontology, "version": "0.1.0"},
    }
    digest = content_hash(doc)
    return {"id": f"urn:duly:fact:sha256:{digest}", "contentHash": digest, **doc}


def build_notice_facts(
    template: dict,
    case_id: str,
    *,
    expiration: _dt.date,
    margin: int,
    nonpayment: bool,
    mailed_confidence: dict | None = None,
    expiration_confidence: dict | None = None,
) -> tuple[list[dict], str, str]:
    """Facts + asOf points for one termination-notice case.

    The notice is mailed `margin` days before `expiration`; asOf.effective is
    the mailed date, asOf.knowledge two days later. The optional confidence
    overrides exercise the pack's abstentionPolicy (mailed date carries a
    per-attribute floor, expiration date the pack default).
    """
    mailed = expiration - _dt.timedelta(days=margin)
    ts = f"{mailed.isoformat()}T12:00:00Z"
    case_ref = f"case:golden:{case_id}"
    notice_id = f"notice:{case_id}"
    policy_id = f"policy:{case_id}"
    ontology = template["ontology"]
    facts = [
        make_fact(
            case_ref, notice_id, "nc:TerminationNotice", "nc:noticeType",
            {
                "kind": "code",
                "value": template["notice_type"],
                "codeSystem": "duly-starter-notice/notice-types",
                "codeSystemVersion": "0.1.0",
            },
            ontology, ts,
        ),
        make_fact(
            case_ref, notice_id, "nc:TerminationNotice", "nc:noticeMailedDate",
            {"kind": "date", "value": mailed.isoformat()},
            ontology, ts,
            confidence=mailed_confidence,
        ),
        make_fact(
            case_ref, policy_id, "nc:Policy", "nc:governingState",
            {
                "kind": "code",
                "value": template["state"],
                "codeSystem": "iso-3166-2",
                "codeSystemVersion": "2020",
            },
            ontology, ts,
        ),
        make_fact(
            case_ref, policy_id, "nc:Policy", "nc:policyExpirationDate",
            {"kind": "date", "value": expiration.isoformat()},
            ontology, ts,
            confidence=expiration_confidence,
        ),
    ]
    if nonpayment:
        facts.append(
            make_fact(
                case_ref, notice_id, "nc:TerminationNotice", "nc:terminationGround",
                {
                    "kind": "code",
                    "value": "Nonpayment",
                    "codeSystem": "duly-starter-notice/termination-grounds",
                    "codeSystemVersion": "0.1.0",
                },
                ontology, ts,
            )
        )
    as_of_effective = mailed.isoformat()
    as_of_knowledge = f"{(mailed + _dt.timedelta(days=2)).isoformat()}T12:00:00Z"
    return facts, as_of_effective, as_of_knowledge


def draw_notice_params(template: dict, rng: random.Random) -> dict:
    span = (EXPIRATION_END - EXPIRATION_START).days
    lo, hi = template["margin_days"]
    params = {
        "expiration": EXPIRATION_START + _dt.timedelta(days=rng.randrange(span + 1)),
        "margin": rng.randint(lo, hi),
        "nonpayment": rng.random() < template["nonpayment_share"],
    }
    # Confidence draws exercising the pack's abstentionPolicy
    # (nc:noticeMailedDate floor 0.9 per-attribute, default 0.75), on both
    # sides of each boundary. None = the make_fact default (1.0 raw).
    r = rng.random()
    if r < 0.05:
        # Below the per-attribute floor AND the pack default: excluded.
        params["mailed_confidence"] = {"score": 0.6, "method": "platt"}
    elif r < 0.10:
        # Above the 0.75 default but below the 0.9 override: excluded only
        # because the per-attribute floor beats the default.
        params["mailed_confidence"] = {"score": 0.85, "method": "platt"}
    elif r < 0.15:
        # Exactly at the per-attribute floor: binds (at-floor is inclusive).
        params["mailed_confidence"] = {"score": 0.9, "method": "platt"}
    else:
        params["mailed_confidence"] = None
    r = rng.random()
    if r < 0.04:
        # Below the pack default floor (no override on this attribute): excluded.
        params["expiration_confidence"] = {"score": 0.7, "method": "temperature"}
    elif r < 0.08:
        # Exactly at the default floor: binds.
        params["expiration_confidence"] = {"score": 0.75, "method": "temperature"}
    else:
        params["expiration_confidence"] = None
    return params


def _cents(c: int) -> str:
    return f"{c // 100}.{c % 100:02d}"


def build_trid_facts(
    template: dict,
    case_id: str,
    *,
    disclosed_cents: int,
    actual_cents: int,
) -> tuple[list[dict], str, str]:
    """Facts + asOf points for one TRID transfer-tax tolerance case."""
    closing = _dt.date.fromisoformat(template["as_of_effective"])
    ts = f"{closing.isoformat()}T12:00:00Z"
    case_ref = f"case:golden:{case_id}"
    fee_id = f"fee:transfer-tax:{case_id}"
    ontology = template["ontology"]
    facts = [
        make_fact(
            case_ref, fee_id, "trid:Fee", "trid:feeType",
            {
                "kind": "code",
                "value": "TransferTax",
                "codeSystem": "duly-starter-trid/fee-types",
                "codeSystemVersion": "0.1.0",
            },
            ontology, ts,
        ),
        make_fact(
            case_ref, fee_id, "trid:Fee", "trid:disclosedAmountAtBaseline",
            {"kind": "money", "amount": _cents(disclosed_cents), "currency": "USD"},
            ontology, ts,
        ),
        make_fact(
            case_ref, fee_id, "trid:Fee", "trid:actualAmountAtClosing",
            {"kind": "money", "amount": _cents(actual_cents), "currency": "USD"},
            ontology, ts,
        ),
    ]
    as_of_effective = closing.isoformat()
    as_of_knowledge = f"{(closing + _dt.timedelta(days=2)).isoformat()}T12:00:00Z"
    return facts, as_of_effective, as_of_knowledge


def draw_trid_params(template: dict, rng: random.Random) -> dict:
    disclosed = rng.randint(20000, 480000)  # $200.00 .. $4800.00 in cents
    r = rng.random()
    if r < 0.45:  # increase (including small ones near the baseline)
        actual = disclosed + rng.randint(1, 60000)
    elif r < 0.75:  # equal
        actual = disclosed
    else:  # decrease
        actual = disclosed - rng.randint(1, min(disclosed - 100, 40000))
    return {"disclosed_cents": disclosed, "actual_cents": actual}


# ---------------------------------------------------------------------------
# Generation driver
# ---------------------------------------------------------------------------


def repo_root() -> Path:
    root = Path(__file__).resolve().parents[2]
    if (root / "spec" / "schemas").is_dir():
        return root
    return Path.cwd()


def _fact_validator(root: Path):
    from jsonschema import Draft202012Validator, FormatChecker

    schema = json.loads((root / "spec" / "schemas" / "grounded-fact.schema.json").read_text())
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _validate_fact(validator, fact: dict) -> None:
    errors = list(validator.iter_errors(fact))
    if errors:
        msgs = "; ".join(e.message for e in errors)
        raise ValueError(f"generated fact failed schema validation: {msgs}")


def allocate(count: int, names: list[str]) -> dict[str, int]:
    """Split `count` across templates proportionally to their registry
    weights (largest-remainder, ties broken by registry order). Purely
    integer arithmetic, so allocation is deterministic."""
    weights = {n: STATE_TEMPLATES[n]["weight"] for n in names}
    total = sum(weights.values())
    quotas: dict[str, int] = {}
    remainders: list[tuple[int, int, str]] = []
    for idx, n in enumerate(names):
        q, r = divmod(count * weights[n], total)
        quotas[n] = q
        remainders.append((-r, idx, n))
    for _, _, n in sorted(remainders)[: count - sum(quotas.values())]:
        quotas[n] += 1
    return quotas


def _generate_case(template: dict, case_id: str, rng: random.Random, pack: dict, validator):
    for _ in range(20):
        if template["kind"] == "notice":
            params = draw_notice_params(template, rng)
            facts, eff, kn = build_notice_facts(template, case_id, **params)
        elif template["kind"] == "trid":
            params = draw_trid_params(template, rng)
            facts, eff, kn = build_trid_facts(template, case_id, **params)
        else:  # pragma: no cover - registry entries are internal data
            raise ValueError(f"unknown template kind: {template['kind']!r}")
        for fact in facts:
            _validate_fact(validator, fact)
        try:
            receipt = adjudicate(facts, pack, eff, kn, template["question"])
        except AdjudicationError:
            # Deterministic redraw: discard this draw, take the next one from
            # the same stream; the case id does not advance.
            continue
        return facts, eff, kn, receipt
    raise AdjudicationError(f"could not draw a valid case for {case_id} after 20 attempts")


def _dump_json(doc: dict) -> str:
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def _write_case(out: Path, case_id: str, template: dict, eff: str, kn: str, facts: list[dict], receipt: dict) -> None:
    case_dir = out / "cases" / case_id
    (case_dir / "facts").mkdir(parents=True)
    case_yaml = (
        f"id: {case_id}\n"
        f"pack: {template['pack']}\n"
        f"question: {template['question']}\n"
        f"asOfEffective: \"{eff}\"\n"
        f"asOfKnowledge: \"{kn}\"\n"
    )
    (case_dir / "case.yaml").write_text(case_yaml, encoding="utf-8")
    for fact in facts:
        name = fact["attribute"].replace(":", "-") + ".json"
        (case_dir / "facts" / name).write_text(_dump_json(fact), encoding="utf-8")
    (out / "receipts" / f"{case_id}.json").write_text(_dump_json(receipt), encoding="utf-8")


def _decision_label(receipt: dict) -> str:
    v = receipt["decision"]["value"]
    if v["kind"] == "boolean":
        return "compliant" if v["value"] else "non-compliant"
    if v["kind"] == "money":
        return "no-cure" if Decimal(v["amount"]) == 0 else "cure-owed"
    return "other"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m duly_assurance generate",
        description="Generate the golden corpus (deterministic; see golden/README.md).",
    )
    parser.add_argument("--out", default="golden", help="output directory (default: golden)")
    parser.add_argument("--count", type=int, default=250, help="total cases across templates")
    parser.add_argument("--seed", type=int, default=7, help="generator seed")
    parser.add_argument(
        "--templates",
        default=None,
        help="comma-separated template names (default: all registered)",
    )
    args = parser.parse_args(argv)

    if args.templates:
        names = [n.strip() for n in args.templates.split(",") if n.strip()]
        unknown = [n for n in names if n not in STATE_TEMPLATES]
        if unknown:
            known = ", ".join(STATE_TEMPLATES)
            print(f"unknown template(s): {', '.join(unknown)} (registered: {known})", file=sys.stderr)
            return 2
    else:
        names = list(STATE_TEMPLATES)
    if args.count < 1:
        print("--count must be at least 1", file=sys.stderr)
        return 2

    root = repo_root()
    out = Path(args.out)
    validator = _fact_validator(root)
    quotas = allocate(args.count, names)

    # Generate everything in memory first so a failure leaves the existing
    # corpus untouched, then reset cases/ + receipts/ and write.
    generated: list[tuple[str, str, dict, str, str, list[dict], dict]] = []
    packs: dict[str, dict] = {}
    for name in names:
        template = STATE_TEMPLATES[name]
        pack_rel = template["pack"]
        if pack_rel not in packs:
            packs[pack_rel] = yaml.safe_load((root / pack_rel).read_text())
        rng = random.Random(f"{args.seed}:{name}")
        for i in range(1, quotas[name] + 1):
            case_id = f"{template['id_prefix']}-{i:04d}"
            facts, eff, kn, receipt = _generate_case(template, case_id, rng, packs[pack_rel], validator)
            generated.append((name, case_id, template, eff, kn, facts, receipt))

    for sub in ("cases", "receipts"):
        sub_dir = out / sub
        if sub_dir.exists():
            shutil.rmtree(sub_dir)
        sub_dir.mkdir(parents=True)
    for _, case_id, template, eff, kn, facts, receipt in generated:
        _write_case(out, case_id, template, eff, kn, facts, receipt)

    print(f"generated {len(generated)} cases into {out}")
    for name in names:
        rows = [g for g in generated if g[0] == name]
        labels: dict[str, int] = {}
        for row in rows:
            label = _decision_label(row[6])
            labels[label] = labels.get(label, 0) + 1
        split = ", ".join(f"{v} {k}" for k, v in sorted(labels.items()))
        print(f"  {name}: {len(rows)} cases ({split})")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
