#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["ortools>=9.8", "duly"]
#
# [tool.uv.sources]
# duly = { path = "../..", editable = true }
# ///
#
# The block above is PEP 723 inline script metadata, and it is where CP-SAT is
# declared *for the whole repository*. There is no `scheduling` extra in the
# root `pyproject.toml`: ortools belongs to this example, not to duly, so its
# declaration lives in the file that needs it and leaves with `git rm -r
# examples/`. `uv run examples/closing-scheduler/schedule.py` resolves it.
#
# `duly` is listed too, from a relative path source, because a script with
# inline metadata runs in its own environment rather than the project's — the
# same isolation that makes the ortools declaration self-contained also means
# nothing is on the path unless this block says so. The path is relative to
# this file, so the example still moves as a directory.
"""Plan a mortgage closing — sign, fund, record — to the earliest feasible dates.

    uv run examples/closing-scheduler/schedule.py

duly decides what is ALLOWED. The solver decides what is BEST. A compliance
rule is never re-encoded here.

Concretely, that boundary is mechanical rather than aspirational:

- Every hard constraint this module hands CP-SAT is a table of day indices
  (or (sign, fund) pairs) that `duly_kernel.api.adjudicate` actually
  permitted, built in `probe_windows` and nowhere else. There is no other
  path from a rule to the model.
- The only constraints this module writes itself are operational — who is
  available on which day, and the local policy that recording follows
  funding. They come from the `operational` block of the closing file, they
  are labelled DEMO-SYNTHETIC there, and they mention no statute.
- Grep the file for a legal concept and you will find it only in comments and
  in citation strings copied out of receipts. There is no business-day walk,
  no three-day count, no state RON table, no top-margin threshold. There
  cannot be: the scheduler never sees a rule, only a verdict and a receipt id.

The output is the differentiator: each chosen date cites the receipt ids that
constrained it, so the plan is auditable in the same way a decision is. A
scheduler that merely produces dates gives an auditor nothing to check.

Determinism (a repo invariant, and CP-SAT violates it by default): the
planning date is an input — nothing here reads the clock — the solver runs
with one worker and a fixed seed, the objective has a unique optimum by
construction, and every set that reaches the model is sorted first.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# The kernel is the only thing that decides anything. `content_hash` comes from
# the fact store rather than being reimplemented: an orchestrator that mints
# facts is a fact-store client, and a second copy of the content-addressing
# rule is exactly the kind of drift CLAUDE.md's "Content addressing" invariant
# exists to prevent.
from duly_kernel.api import adjudicate
from duly_store.store import content_hash

try:  # The solver is optional; the compliance half of this example is not.
    from ortools.sat.python import cp_model
except ImportError:  # pragma: no cover - exercised by test_scheduler.py
    cp_model = None  # type: ignore[assignment]

ORTOOLS_MISSING = (
    "ortools is not installed. The scheduler half of this example is behind an\n"
    "optional dependency (the duly half is not). This file declares it in its\n"
    "own PEP 723 script metadata, so the shortest path is to let uv read it:\n"
    "    uv run examples/closing-scheduler/schedule.py\n"
    "or, from an environment you manage yourself,\n"
    "    uv run --with ortools python examples/closing-scheduler/schedule.py\n"
    "\n"
    "To see the adjudicated windows without a solver, run with --no-solve."
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CLOSING_FILE = Path(__file__).resolve().parent / "closing-file.json"

WEEKDAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


# ---------------------------------------------------------------------------
# The gates: which pack answers which question about which step
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Gate:
    """One compliance question standing between a step and its date.

    `required` is the answer that permits the step. Anything else — a
    different value, an abstention, a pack that reaches no conclusion —
    forbids it. Failing closed is the point: `county-recording-us` reaches no
    decision at all for a state it does not encode, and a scheduler that read
    "no decision" as "fine" would book a rejected recording.
    """

    step: str
    pack_path: str
    question: str
    required: bool
    why: str


# The registry is data, not dispatch (CLAUDE.md, "Auto-discovery over
# registration"): adding a fourth gate is a tuple entry, and the probe,
# the model and the report all pick it up.
GATES: tuple[Gate, ...] = (
    Gate(
        step="sign",
        pack_path="examples/rulepacks/notarization-ron-us-states/pack.yaml",
        question="ron:ronPermitted",
        required=True,
        why="whether the governing state authorized remote online notarization on that date",
    ),
    Gate(
        step="sign",
        pack_path="examples/rulepacks/notarization-ron-us-states/pack.yaml",
        question="ron:notarizationCompliant",
        required=True,
        why="whether the notarial act, performed the planned way on that date, is compliant",
    ),
    Gate(
        step="fund",
        pack_path="examples/rulepacks/tila-rescission-us-federal/pack.yaml",
        question="resc:fundingPermitted",
        required=True,
        why="whether the TILA rescission period has expired, given the signing date",
    ),
    Gate(
        step="record",
        pack_path="examples/rulepacks/county-recording-us/pack.yaml",
        question="rec:recordable",
        required=True,
        why="whether the instrument will be accepted for recording as submitted",
    ),
)

# ron:ronPermitted is reported for every candidate signing day but is NOT the
# gate on its own: an in-person notarization is compliant in a state that has
# never authorized RON. `ron:notarizationCompliant` is the rule that combines
# the two, so it is the one that binds. Both receipts are cited, because "we
# checked whether RON was available and it was not, and it did not matter"
# is exactly the kind of thing an auditor asks about.
BINDING_SIGN_QUESTION = "ron:notarizationCompliant"


# ---------------------------------------------------------------------------
# Minting facts from the closing file
# ---------------------------------------------------------------------------

def _strip_notes(obj):
    """Drop `$`-prefixed annotation keys — the closing file documents itself."""
    if isinstance(obj, dict):
        return {k: _strip_notes(v) for k, v in obj.items() if not k.startswith("$")}
    if isinstance(obj, list):
        return [_strip_notes(v) for v in obj]
    return obj


def mint_fact(closing: dict, entity_key: str, attribute: str, value: dict) -> dict:
    """A content-addressed GroundedFact carrying one closing-file value.

    These are ATTESTATIONS, not extractions, and the distinction is load-
    bearing rather than a convenience. A closing that has not happened yet has
    no documents to extract from: "we intend to consummate on the 17th" is a
    statement a human coordinator owns, so it is grounded as one. That is also
    why a plan is a forecast and not a finding — see the README's "what this
    deliberately does not do". Swap these for extractor-produced facts (see
    `starters/` for span-grounded facts on exactly these attributes) and
    nothing else in this file changes.
    """
    attestor = closing["attestor"]
    body = {
        "caseId": closing["caseId"],
        "entity": dict(closing["entities"][entity_key]),
        "attribute": attribute,
        "value": value,
        "grounding": {
            "kind": "attestation",
            "actor": attestor["actor"],
            "channel": attestor["channel"],
            "at": closing["plan"]["attestedAt"],
        },
        "assertion": {
            "kind": "human",
            "at": closing["plan"]["attestedAt"],
            "actor": {"id": attestor["actor"], "role": attestor["role"]},
        },
        "recordedAt": closing["plan"]["attestedAt"],
        "status": "asserted",
        "schemaRef": dict(closing["schemaRef"]),
    }
    digest = content_hash(body)
    return {"id": f"urn:duly:fact:sha256:{digest}", "contentHash": digest, **body}


def facts_for(closing: dict, signing_date: str | None = None) -> list[dict]:
    """The closing file's known facts, plus the planned signing-date triggers.

    A different candidate signing date is a different fact — new value, new
    content hash, new id. Nothing is mutated in place (CLAUDE.md, "Content
    addressing").
    """
    facts = [
        mint_fact(closing, item["entity"], item["attribute"], item["value"])
        for item in closing["known"]
    ]
    if signing_date is not None:
        block = closing["signingDateAttributes"]
        facts.extend(
            mint_fact(closing, block["entity"], attribute, {"kind": "date", "value": signing_date})
            for attribute in block["attributes"]
        )
    return facts


# ---------------------------------------------------------------------------
# Probing: turning the packs into tables of permitted days
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Adjudication:
    """One kernel run, reduced to what a plan needs to cite it.

    `receipt_id` is None when the pack reached no conclusion. That is a real
    and frequent outcome — `county-recording-us` fails closed for an unencoded
    state — and it has NO receipt, because no decision was made. A plan must
    not pretend otherwise, so the refusal is carried as `error` and rendered
    as such.
    """

    step: str
    question: str
    pack: str
    as_of: str
    signing_date: str | None
    permitted: bool
    rendered: str
    receipt_id: str | None
    rules: tuple[str, ...]
    citations: tuple[str, ...]
    error: str | None

    def cite(self) -> dict:
        out: dict = {
            "question": self.question,
            "asOfEffective": self.as_of,
            "pack": self.pack,
            "answer": self.rendered,
        }
        if self.signing_date is not None:
            out["givenSigningDate"] = self.signing_date
        if self.receipt_id is not None:
            out["receipt"] = self.receipt_id
            out["rulesFired"] = list(self.rules)
            if self.citations:
                out["authority"] = list(self.citations)
        else:
            out["receipt"] = None
            out["noReceiptBecause"] = self.error
        return out


class Probe:
    """Every adjudication a run performed, kept so the plan can cite them."""

    def __init__(self, closing: dict, repo_root: Path):
        self.closing = closing
        self.repo_root = repo_root
        self.packs: dict[str, dict] = {}
        self.receipts: dict[str, dict] = {}
        self.count = 0

    def pack(self, rel_path: str) -> dict:
        if rel_path not in self.packs:
            self.packs[rel_path] = yaml.safe_load(
                (self.repo_root / rel_path).read_text(encoding="utf-8")
            )
        return self.packs[rel_path]

    def ask(self, gate: Gate, as_of: str, signing_date: str | None = None) -> Adjudication:
        pack = self.pack(gate.pack_path)
        meta = pack["pack"]
        facts = facts_for(self.closing, signing_date)
        self.count += 1
        try:
            receipt = adjudicate(
                facts,
                pack,
                as_of,
                self.closing["plan"]["asOfKnowledge"],
                gate.question,
            )
        except Exception as exc:  # noqa: BLE001 - every failure mode is "no decision"
            return Adjudication(
                step=gate.step,
                question=gate.question,
                pack=f"{meta['name']}@{meta['version']}",
                as_of=as_of,
                signing_date=signing_date,
                permitted=False,
                rendered="(no decision)",
                receipt_id=None,
                rules=(),
                citations=(),
                error=f"{type(exc).__name__}: {exc}",
            )
        self.receipts[receipt["id"]] = receipt
        value = receipt["decision"]["value"]
        answer = value.get("value")
        return Adjudication(
            step=gate.step,
            question=gate.question,
            pack=f"{meta['name']}@{meta['version']}",
            as_of=as_of,
            signing_date=signing_date,
            permitted=answer is gate.required,
            rendered=json.dumps(answer),
            receipt_id=receipt["id"],
            rules=tuple(r["ruleId"] for r in receipt["rulesFired"]),
            citations=tuple(
                dict.fromkeys(
                    r["citation"]["text"]
                    for r in receipt["rulesFired"]
                    if r.get("citation", {}).get("text")
                )
            ),
            error=None,
        )


@dataclass
class Windows:
    """What the packs permitted, as day indices into the planning horizon."""

    days: list[str]
    sign_days: list[int] = field(default_factory=list)
    record_days: list[int] = field(default_factory=list)
    fund_pairs: list[tuple[int, int]] = field(default_factory=list)
    by_sign_day: dict[int, list[Adjudication]] = field(default_factory=dict)
    by_record_day: dict[int, Adjudication] = field(default_factory=dict)
    by_fund_pair: dict[tuple[int, int], Adjudication] = field(default_factory=dict)


def horizon_days(closing: dict) -> list[str]:
    start = dt.date.fromisoformat(closing["plan"]["planningDate"])
    return [
        (start + dt.timedelta(days=offset)).isoformat()
        for offset in range(closing["plan"]["horizonDays"])
    ]


def probe_windows(probe: Probe) -> Windows:
    """Adjudicate every candidate date, and every (sign, fund) pair.

    This function is the ONLY producer of hard constraints in this example.
    Route 1 of the two the README describes: probe by adjudication, read off
    where each decision flips. O(candidates) kernel runs and no optional
    dependency, which is what an embedding is actually shaped like.
    """
    windows = Windows(days=horizon_days(probe.closing))
    sign_gates = [g for g in GATES if g.step == "sign"]
    fund_gate = next(g for g in GATES if g.step == "fund")
    record_gate = next(g for g in GATES if g.step == "record")

    for index, day in enumerate(windows.days):
        answers = [probe.ask(gate, day) for gate in sign_gates]
        windows.by_sign_day[index] = answers
        binding = next(a for a in answers if a.question == BINDING_SIGN_QUESTION)
        if binding.permitted:
            windows.sign_days.append(index)

        recordable = probe.ask(record_gate, day)
        windows.by_record_day[index] = recordable
        if recordable.permitted:
            windows.record_days.append(index)

    # The (sign, fund) table. The funding question is not a property of a date
    # — it is a property of a date GIVEN a signing date, because the pack
    # computes the rescission deadline from the consummation date. So the
    # constraint handed to the solver is a relation, not two intervals, and
    # the solver never learns why the pairs are shaped the way they are.
    for sign_index in windows.sign_days:
        for fund_index in range(sign_index, len(windows.days)):
            answer = probe.ask(
                fund_gate, windows.days[fund_index], signing_date=windows.days[sign_index]
            )
            windows.by_fund_pair[(sign_index, fund_index)] = answer
            if answer.permitted:
                windows.fund_pairs.append((sign_index, fund_index))
    return windows


# ---------------------------------------------------------------------------
# Operational preferences — the ONLY constraints this file writes itself
# ---------------------------------------------------------------------------

def operational_days(closing: dict, step: str) -> list[int]:
    """Day indices on which `step` can operationally happen.

    Availability, and nothing else. If a legal concept ever appears in this
    function, the example has failed at the one thing it is for.
    """
    key = {"sign": "signing", "fund": "funding", "record": "recording"}[step]
    block = closing["operational"][key]
    allowed = set(block["weekdays"])
    unavailable = set(block.get("unavailable", ()))
    days = horizon_days(closing)
    return [
        index
        for index, day in enumerate(days)
        if WEEKDAY_NAMES[dt.date.fromisoformat(day).weekday()] in allowed
        and day not in unavailable
    ]


def operational_reason(closing: dict, step: str, day: str) -> str:
    key = {"sign": "signing", "fund": "funding", "record": "recording"}[step]
    block = closing["operational"][key]
    weekday = WEEKDAY_NAMES[dt.date.fromisoformat(day).weekday()]
    if day in set(block.get("unavailable", ())):
        return f"{day} ({weekday}) is marked unavailable for {key} in the closing file"
    if weekday not in set(block["weekdays"]):
        return f"{day} is a {weekday}; {key} runs {'/'.join(block['weekdays'])}"
    return f"{day} ({weekday}) is available for {key}"


def _why_not_earlier(closing: dict, step: str, days: list[str], first: int, chosen: int) -> list[str]:
    """The operational reason each day from `first` up to `chosen` was skipped.

    `first` is the earliest day compliance allowed. Everything between it and
    the chosen date was rejected by an availability rule, so this list is the
    honest answer to "why not sooner?" — and, read the other way, it is the
    proof that the delay is the scheduler's and not the law's.
    """
    available = set(operational_days(closing, step))
    return [
        operational_reason(closing, step, days[index])
        for index in range(first, chosen)
        if index not in available
    ]


# ---------------------------------------------------------------------------
# The solver
# ---------------------------------------------------------------------------

@dataclass
class Solution:
    status: str
    sign: int | None = None
    fund: int | None = None
    record: int | None = None
    objective: int | None = None


def solve(closing: dict, windows: Windows) -> Solution:
    """Earliest feasible (record, fund, sign), lexicographically.

    Every `AddAllowedAssignments` below is a table `probe_windows` built out
    of kernel verdicts. Every `Add` below is an operational preference from
    the closing file. That is the whole separation, and it is visible in
    eleven lines.
    """
    if cp_model is None:  # pragma: no cover - exercised via monkeypatch
        raise RuntimeError(ORTOOLS_MISSING)

    n = len(windows.days)
    model = cp_model.CpModel()
    sign = model.NewIntVar(0, n - 1, "sign")
    fund = model.NewIntVar(0, n - 1, "fund")
    record = model.NewIntVar(0, n - 1, "record")

    # --- hard constraints: adjudicated, every one of them -------------------
    model.AddAllowedAssignments([sign, fund], sorted(windows.fund_pairs))
    model.AddAllowedAssignments([record], [(d,) for d in sorted(windows.record_days)])

    # --- operational preferences: this file's own, and only these -----------
    for var, step in ((sign, "sign"), (fund, "fund"), (record, "record")):
        model.AddAllowedAssignments(
            [var], [(d,) for d in sorted(operational_days(closing, step))]
        )
    if closing["operational"].get("recordOnOrAfterFunding", True):
        model.Add(record >= fund)

    # Lexicographic (record, fund, sign) as one linear objective. The weights
    # make the optimum UNIQUE — n**2 > n * (n-1) and n > (n-1) — which is what
    # makes the plan byte-stable rather than merely optimal: a tie would let
    # the solver's search order pick the answer.
    model.Minimize(n * n * record + n * fund + sign)

    solver = cp_model.CpSolver()
    # Determinism (CLAUDE.md, "Determinism everywhere"). CP-SAT parallelises
    # and randomises by default, and either one alone makes the plan depend on
    # the machine that produced it. One worker plus a fixed seed removes both.
    # Set `num_workers` ONLY: it and the older alias `num_search_workers` are
    # mutually exclusive, and setting both makes CP-SAT reject the model as
    # MODEL_INVALID — which, before this comment existed, looked exactly like
    # an infeasible closing.
    solver.parameters.num_workers = 1
    solver.parameters.random_seed = 0
    solver.parameters.log_search_progress = False

    status = solver.Solve(model)
    name = solver.StatusName(status)
    if status in (cp_model.MODEL_INVALID, cp_model.UNKNOWN):
        # Not an answer about this closing. Reporting it as "no feasible plan"
        # would be a wrong answer wearing an honest one's clothes.
        raise RuntimeError(
            f"CP-SAT returned {name}, which is a defect in this model rather than a "
            f"statement about the closing: {solver.ResponseStats()}"
        )
    if status != cp_model.OPTIMAL and status != cp_model.FEASIBLE:
        return Solution(status=name)
    return Solution(
        status=name,
        sign=solver.Value(sign),
        fund=solver.Value(fund),
        record=solver.Value(record),
        objective=int(solver.ObjectiveValue()),
    )


# ---------------------------------------------------------------------------
# The audit-linked plan
# ---------------------------------------------------------------------------

def _boundary(windows: Windows, sign_index: int) -> dict:
    """The compliance boundary for funding, and the receipt that draws it.

    The earliest adjudicated-permitted funding day, plus the kernel's refusal
    of the day before it. Two receipts, and between them they pin the edge:
    this day yes, the previous day no. That pairing is deliberately the same
    shape as a what-if boundary verification (spec/whatif.md, W3) — a claim
    about an edge is worth what its refutation is worth.
    """
    permitted = [f for (s, f) in windows.fund_pairs if s == sign_index]
    if not permitted:
        return {"earliestPermitted": None}
    earliest = min(permitted)
    out: dict = {
        "earliestPermitted": windows.days[earliest],
        "permittedBy": windows.by_fund_pair[(sign_index, earliest)].cite(),
    }
    before = earliest - 1
    if before >= sign_index:
        refusal = windows.by_fund_pair[(sign_index, before)]
        out["refusedTheDayBefore"] = refusal.cite()
    else:
        out["refusedTheDayBefore"] = None
        out["$note"] = (
            "the day before the earliest permitted funding day falls before the "
            "signing date, so there is no adjudication to cite for it"
        )
    return out


def build_plan(closing: dict, windows: Windows, solution: Solution, probe: Probe) -> dict:
    days = windows.days
    plan: dict = {
        "example": "examples/closing-scheduler",
        "case": closing["caseId"],
        "title": closing["title"],
        "planningDate": closing["plan"]["planningDate"],
        "horizon": {"from": days[0], "to": days[-1]},
        "status": "PLANNED" if solution.sign is not None else "NO-FEASIBLE-PLAN",
    }

    if solution.sign is None:
        plan["blocked"] = _blockers(closing, windows)
        plan["solver"] = {"status": solution.status, "randomSeed": 0, "workers": 1}
        plan["adjudications"] = _adjudication_summary(probe)
        return plan

    def step_entry(
        step: str, index: int, compliance: dict, floor: int, floor_label: str, floor_note: str
    ) -> dict:
        day = days[index]
        return {
            "step": step,
            "date": day,
            "weekday": WEEKDAY_NAMES[dt.date.fromisoformat(day).weekday()],
            # The whole thesis in one field: which layer put this date here.
            # "compliance" means a duly answer is the binding constraint;
            # "sequencing" means a local step-order policy is; "operational"
            # means duly permitted an earlier date and the closing file's own
            # availability pushed it out.
            "boundBy": floor_label if index == floor else "operational",
            "compliance": compliance,
            "floor": {
                "earliestAllowed": days[floor],
                "setBy": floor_label,
                "because": floor_note,
            },
            "operational": {
                "chosenDayIsAvailable": operational_reason(closing, step, day),
                "whyNotEarlier": _why_not_earlier(closing, step, days, floor, index),
            },
        }

    steps = []

    earliest_sign = min(windows.sign_days)
    steps.append(
        step_entry(
            "sign",
            solution.sign,
            {
                "permittedBy": [a.cite() for a in windows.by_sign_day[solution.sign]],
                "earliestPermittedInHorizon": days[earliest_sign],
            },
            earliest_sign,
            "compliance",
            "the first day in the horizon whose notarization the RON pack finds compliant",
        )
    )

    boundary = _boundary(windows, solution.sign)
    earliest_fund = min(f for (s, f) in windows.fund_pairs if s == solution.sign)
    steps.append(
        step_entry(
            "fund",
            solution.fund,
            {
                "permittedBy": [windows.by_fund_pair[(solution.sign, solution.fund)].cite()],
                "boundary": boundary,
            },
            earliest_fund,
            "compliance",
            "the day the TILA rescission period expires for the chosen signing date",
        )
    )

    # Recording's floor is the later of what the recording pack permits and
    # what the closing file's own record-after-funding policy allows. The
    # second half is operational, and is named as such so the two are never
    # confused for one another.
    earliest_record_pack = min(windows.record_days)
    follows_funding = closing["operational"].get("recordOnOrAfterFunding", True)
    earliest_record = (
        max(earliest_record_pack, solution.fund) if follows_funding else earliest_record_pack
    )
    sequenced = follows_funding and earliest_record > earliest_record_pack
    steps.append(
        step_entry(
            "record",
            solution.record,
            {
                "permittedBy": [windows.by_record_day[solution.record].cite()],
                "earliestPermittedInHorizon": days[earliest_record_pack],
            },
            earliest_record,
            "sequencing" if sequenced else "compliance",
            (
                "the funding date, under the closing file's own record-on-or-after-funding "
                f"policy — an operational choice, not law; the recording pack itself permits "
                f"{days[earliest_record_pack]}"
                if sequenced
                else "the first day in the horizon the recording pack finds the instrument recordable"
            ),
        )
    )

    plan["plan"] = steps
    plan["solver"] = {
        "status": solution.status,
        "objective": solution.objective,
        "randomSeed": 0,
        "workers": 1,
        "objectiveOrder": ["record", "fund", "sign"],
    }
    plan["adjudications"] = _adjudication_summary(probe)
    return plan


def _blockers(closing: dict, windows: Windows) -> list[dict]:
    """Why there is no plan — with the receipt that says so, where one exists."""
    out: list[dict] = []
    if not windows.sign_days:
        first = windows.by_sign_day[0]
        out.append(
            {
                "step": "sign",
                "reason": "no candidate date in the horizon has a compliant notarization",
                "adjudications": [a.cite() for a in first],
            }
        )
    if not windows.record_days:
        out.append(
            {
                "step": "record",
                "reason": "no candidate date in the horizon has a recordable submission",
                "adjudications": [windows.by_record_day[0].cite()],
            }
        )
    if windows.sign_days and not windows.fund_pairs:
        out.append(
            {
                "step": "fund",
                "reason": "no (signing, funding) pair in the horizon permits disbursement",
                "adjudications": [
                    windows.by_fund_pair[(windows.sign_days[0], len(windows.days) - 1)].cite()
                ],
            }
        )
    if not out:
        out.append(
            {
                "step": "*",
                "reason": (
                    "every gate has a permitted date, but no combination also satisfies "
                    "the operational preferences in the closing file"
                ),
                "adjudications": [],
            }
        )
    return out


def _adjudication_summary(probe: Probe) -> dict:
    return {
        "kernelRuns": probe.count,
        "distinctReceipts": len(probe.receipts),
        "packs": sorted(
            f"{p['pack']['name']}@{p['pack']['version']}" for p in probe.packs.values()
        ),
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render(plan: dict) -> str:
    lines = [
        f"closing plan — {plan['title']}",
        f"  case             {plan['case']}",
        f"  planning date    {plan['planningDate']}  (an input; nothing here reads the clock)",
        f"  horizon          {plan['horizon']['from']} .. {plan['horizon']['to']}",
        f"  status           {plan['status']}",
        "",
    ]
    if plan["status"] != "PLANNED":
        lines.append("no feasible plan. what stopped it:")
        for block in plan["blocked"]:
            lines.append(f"  [{block['step']}] {block['reason']}")
            for cite in block["adjudications"]:
                lines.extend("      " + s for s in _cite_lines(cite))
        lines.append("")
    else:
        for step in plan["plan"]:
            lines.append(
                f"  {step['step']:<7}{step['date']}  ({step['weekday']})"
                f"   bound by: {step['boundBy'].upper()}"
            )
            for cite in step["compliance"]["permittedBy"]:
                lines.extend("      " + s for s in _cite_lines(cite))
            boundary = step["compliance"].get("boundary")
            if boundary and boundary.get("earliestPermitted"):
                lines.append(
                    f"      the boundary, kernel-checked from both sides "
                    f"(opens {boundary['earliestPermitted']}):"
                )
                lines.extend("        " + s for s in _cite_lines(boundary["permittedBy"]))
                if boundary.get("refusedTheDayBefore"):
                    lines.extend(
                        "        " + s for s in _cite_lines(boundary["refusedTheDayBefore"])
                    )
            floor = step["floor"]
            lines.append(
                f"      earliest allowed {floor['earliestAllowed']} "
                f"({floor['setBy']}) — {floor['because']}"
            )
            skipped = step["operational"]["whyNotEarlier"]
            if skipped:
                lines.append("      pushed later by availability, not by law:")
                for reason in skipped[:4]:
                    lines.append(f"        {reason}")
                if len(skipped) > 4:
                    lines.append(f"        ... and {len(skipped) - 4} more unavailable days")
            lines.append(f"      {step['operational']['chosenDayIsAvailable']}")
            lines.append("")

    summary = plan["adjudications"]
    lines.append(
        f"{summary['kernelRuns']} kernel runs, {summary['distinctReceipts']} distinct receipts, "
        f"packs: {', '.join(summary['packs'])}"
    )
    lines.append(
        "every date above is permitted by a receipt an auditor can replay; "
        "no rule was re-encoded in the scheduler."
        if plan["status"] == "PLANNED"
        else "the refusal above is a receipt an auditor can replay; "
        "the scheduler was never told what the rule is."
    )
    return "\n".join(lines)


def _cite_lines(cite: dict) -> list[str]:
    given = f" given signing {cite['givenSigningDate']}" if cite.get("givenSigningDate") else ""
    head = f"{cite['question']} = {cite['answer']}  @ {cite['asOfEffective']}{given}"
    out = [head, f"  {cite['pack']}"]
    if cite.get("receipt"):
        out.append(f"  receipt {cite['receipt']}")
        out.append(f"  rules   {', '.join(cite['rulesFired'])}")
        for authority in cite.get("authority", []):
            out.append(f"  cites   {authority}")
    else:
        out.append(f"  no receipt — {cite['noReceiptBecause']}")
    return out


def render_windows(closing: dict, windows: Windows) -> str:
    """The adjudicated windows alone — what duly said, before any solving."""
    lines = ["adjudicated windows (no solver involved):"]
    sign = [windows.days[d] for d in windows.sign_days]
    record = [windows.days[d] for d in windows.record_days]
    lines.append(f"  signing permitted on  {len(sign)}/{len(windows.days)} candidate days")
    lines.append(f"    {sign[0]} .. {sign[-1]}" if sign else "    (none)")
    lines.append(f"  recording permitted on {len(record)}/{len(windows.days)} candidate days")
    lines.append(f"    {record[0]} .. {record[-1]}" if record else "    (none)")
    lines.append(f"  funding permitted for {len(windows.fund_pairs)} (signing, funding) pairs")
    for sign_index in windows.sign_days[:5]:
        opens = [f for (s, f) in windows.fund_pairs if s == sign_index]
        opens_on = windows.days[min(opens)] if opens else "(never in horizon)"
        lines.append(f"    sign {windows.days[sign_index]} -> funding opens {opens_on}")
    if len(windows.sign_days) > 5:
        lines.append(f"    ... {len(windows.sign_days) - 5} more signing days")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def load_closing(path: Path) -> dict:
    """Read a closing file, resolving one level of `extends`.

    A variant file says what is different about the closing and nothing else,
    so the reader can see the single changed attribute rather than diff two
    near-identical documents. `override.known` replaces a base entry with the
    same (entity, attribute); everything else is a top-level replacement.
    """
    doc = _strip_notes(json.loads(path.read_text(encoding="utf-8")))
    parent = doc.pop("extends", None)
    if parent is None:
        return doc
    base = load_closing(path.parent / parent)
    override = doc.pop("override", {})
    base.update(doc)
    for item in override.get("known", ()):
        key = (item["entity"], item["attribute"])
        base["known"] = [
            item if (k["entity"], k["attribute"]) == key else k for k in base["known"]
        ]
    for section, patch in override.items():
        if section != "known":
            base[section] = {**base.get(section, {}), **patch}
    return base


def plan_closing(closing: dict, repo_root: Path = REPO_ROOT) -> tuple[dict, Windows, Probe]:
    """Probe, solve, and build the audit-linked plan. The library entry point."""
    probe = Probe(closing, repo_root)
    windows = probe_windows(probe)
    solution = solve(closing, windows)
    return build_plan(closing, windows, solution, probe), windows, probe


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Plan a mortgage closing against duly adjudications with CP-SAT.",
    )
    parser.add_argument(
        "--closing-file",
        type=Path,
        default=DEFAULT_CLOSING_FILE,
        help="the closing file to plan (default: this example's California refinance)",
    )
    parser.add_argument("--json", action="store_true", help="emit the plan as JSON")
    parser.add_argument(
        "--no-solve",
        action="store_true",
        help="print the adjudicated windows only; needs no solver",
    )
    parser.add_argument(
        "--receipts-out",
        type=Path,
        default=None,
        help="write every receipt this run produced to a directory, so the cited ids resolve",
    )
    args = parser.parse_args(argv)

    closing = load_closing(args.closing_file)

    if args.no_solve:
        probe = Probe(closing, REPO_ROOT)
        windows = probe_windows(probe)
        _write_receipts(args.receipts_out, probe)
        print(render_windows(closing, windows))
        return 0

    if cp_model is None:
        print(ORTOOLS_MISSING, file=sys.stderr)
        return 2

    plan, _windows, probe = plan_closing(closing)
    _write_receipts(args.receipts_out, probe)
    if args.json:
        print(json.dumps(plan, indent=2, ensure_ascii=False))
    else:
        print(render(plan))
    return 0 if plan["status"] == "PLANNED" else 1


def _write_receipts(directory: Path | None, probe: Probe) -> None:
    if directory is None:
        return
    directory.mkdir(parents=True, exist_ok=True)
    for receipt_id, receipt in sorted(probe.receipts.items()):
        name = receipt_id.rsplit(":", 1)[-1]
        (directory / f"{name}.json").write_text(
            json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    raise SystemExit(main())
