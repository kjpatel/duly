#!/usr/bin/env python3
"""A solver runs the rulebase backwards, and the kernel checks its homework.

`python -m duly_whatif` frees one input of a decided case and asks which of
its values produce a target decision — the latest compliant mailing date, the
largest fee that owes no cure, the earliest date funds may be disbursed. The
questions a compliance operator actually asks are shaped like that, and a
receipt cannot answer any of them: a receipt says what was decided, not what
would have had to be true.

The claim being demonstrated is not "Z3 can solve constraints". It is that a
solver's answer about a hypothetical is a *proposal*, and that a proposal
becomes an answer only when the real kernel has run on the real fact set and
agreed. Every figure printed below was produced twice: once by the solver,
and once by `duly_kernel.api.adjudicate` on a reconstructed, re-addressed case.

The last section is the one worth reading twice. It hands the solver a
deliberately broken encoding and shows the tool refusing to answer rather
than returning the plausible, wrong date that encoding implies.

Nothing here touches adjudication. Like `prove`, what-if is analysis beside
the decision path rather than inside it: no solver output reaches a receipt.

Run from the repo root:

    uv run --with z3-solver python spec/whatif_demo.py

Design decisions and their rationale: spec/whatif.md. Determinism note: an
extremal is a property of the constraint set rather than of the solver's
search, so this script prints the same bytes on every run — like every other
example in this repo, and for the same reason.
"""
from __future__ import annotations

import copy
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from duly_conformance.registry import load_repo_registry  # noqa: E402
from duly_whatif import query as query_module  # noqa: E402
from duly_whatif.query import (  # noqa: E402
    Query,
    SolverKernelContradiction,
    solve,
)

GOLDEN = ROOT / "golden" / "cases"


def rule(text: str) -> None:
    print()
    print(text)
    print("-" * len(text))


def load(case_id: str):
    directory = GOLDEN / case_id
    case = yaml.safe_load((directory / "case.yaml").read_text())
    facts = [
        json.loads(p.read_text()) for p in sorted((directory / "facts").glob("*.json"))
    ]
    pack = yaml.safe_load((ROOT / str(case["pack"])).read_text())
    return case, facts, pack


def ask(case_id: str, free: str, **overrides) -> None:
    """Run one what-if and print it the way the CLI would."""
    from duly_whatif.render import render

    case, facts, pack = load(case_id)
    kwargs = dict(
        facts=facts, pack=pack,
        as_of_effective=str(case["asOfEffective"]),
        as_of_knowledge=str(case["asOfKnowledge"]),
        decision=str(case["question"]), free=free,
    )
    kwargs.update(overrides)
    print(render(solve(Query(**kwargs), REGISTRY)))


REGISTRY = load_repo_registry(ROOT / "ontologies")


# ---------------------------------------------------------------------------

print(__doc__.split("Run from the repo root:")[0].strip())

rule("1. The latest date this notice could have been mailed and stayed compliant")
print("""
golden/cases/notice-ny-0001 is a New York nonrenewal on a policy expiring
2026-06-08, mailed twelve days out and decided NOT compliant. NY-NR-45 has
been in force since 2026-01-01, so the minimum is 45 days — the question the
operator has is "how late could we have left it?", and the pack answers it
backwards.
""".strip())
ask("notice-ny-0001", "nc:noticeMailedDate", target={"kind": "boolean", "value": True})

rule("2. The largest closing amount on this fee that owes no tolerance cure")
print("""
golden/cases/trid-0001 is a transfer tax — a zero-tolerance charge under
1026.19(e)(3)(i) — disclosed at 2984.02 and closed at 3176.76, owing a
192.74 cure. The boundary is exact and it is a money amount, which is why
the search runs on the decimal grid rather than over the reals: over the
reals the answer would be an unattainable infimum that no fact could carry.
""".strip())
ask("trid-0001", "trid:actualAmountAtClosing",
    target={"kind": "money", "amount": "0.00", "currency": "USD"})

rule("3. The earliest date the lender may disburse (TILA, computed calendar)")
print("""
golden/cases/resc-0001 consummates, delivers the notice and delivers the
material disclosures all on 2026-02-12. RESC-DL-01 computes the deadline as
three PRECISE business days later — 12 CFR 1026.2(a)(6), where Saturdays
count and Sundays and 5 U.S.C. 6103(a) holidays do not:

    Fri 2026-02-13   business day 1
    Sat 2026-02-14   business day 2      <- a weekday-only calendar skips this
    Sun 2026-02-15   not a business day
    Mon 2026-02-16   Washington's Birthday, not a business day
    Tue 2026-02-17   business day 3      -> the deadline

Funds may move only once the evaluation date is PAST the deadline day. The
industry's classic bug is conflating this calendar with the general
"creditor's offices are open" one, which drops Saturday the 14th and answers
one day late — in the direction that funds a loan the borrower can still
rescind. The freed input here is the evaluation point itself, which is an
input to the run exactly as a fact is.
""".strip())
ask("resc-0001", "asOf", target={"kind": "boolean", "value": True}, extremal="min")

rule("4. The same arithmetic backwards: how late can closing slip?")
print("""
Funding is scheduled for 2026-02-20. This time consummation is the freed
input and the deadline moves with it.
""".strip())
ask("resc-0001", "resc:consummationDate", target={"kind": "boolean", "value": True},
    as_of_effective="2026-02-20")

rule("5. A flip: how little would have had to change?")
print("""
The interesting flip is the cheapest one, not the most extreme. The reported
boundary is therefore the step BACK toward today's value, which must not
flip — otherwise this was not the nearest change.
""".strip())
ask("notice-ny-0001", "nc:noticeMailedDate", flip=True)

rule("6. Freeing a code input finds a hole the pack did not advertise")
print("""
The notice pack knows New York, Florida and California. Asking which
governing state would make this twelve-day notice compliant answers: none of
them — and any state the pack has never heard of, because nothing concludes
a minimum, so the deficiency rule cannot bind its derived input and the
default presumption of compliance stands. That is a real coverage hole, found
without being told to look for it.

A finite domain is also the one place where "no value works" is fully
verified rather than inferred: every member gets its own kernel run.
""".strip())
ask("notice-ny-0001", "nc:governingState", target={"kind": "boolean", "value": True})

rule("7. UNSATISFIABLE is a weaker claim, and says so")
print("""
No consummation date lets this loan fund on the day it consummates: the
deadline is at least three business days out and consummation is one of the
triggers. True — but not verified, because there is no single point to hand
the kernel. The asymmetry between the two verdicts is the most important
thing this tool has to communicate, so it is printed every time rather than
left in the spec.
""".strip())
ask("resc-0001", "resc:consummationDate", target={"kind": "boolean", "value": True})

rule("8. What happens when the encoding is wrong")
print("""
Everything above rests on one claim: that a solver answer is checked rather
than trusted. A guard that has never fired is a guard nobody can claim, so
here is the guard firing.

The solver is handed the notice pack with its deficiency test perturbed from
`days_between(...) < minDays` to `<= minDays` — a one-character change that
moves the compliance boundary by exactly one day. The kernel keeps running
the real pack.

Note what does NOT save us: the solver's answer, 2026-04-23, is a perfectly
compliant date. The kernel confirms it. A tool that verified only its answer
would return a wrong date that passed its own check. The boundary is what
catches it.
""".strip())

_case, _facts, _pack = load("notice-ny-0001")
_real_encode = query_module._encode


def _broken(pack, registry):
    perturbed = copy.deepcopy(pack)
    for r in perturbed["rules"]:
        if r.get("when"):
            r["when"] = [
                c.replace("days_between(mailed, expiration) < minDays",
                          "days_between(mailed, expiration) <= minDays")
                for c in r["when"]
            ]
    return _real_encode(perturbed, registry)


query_module._encode = _broken
try:
    solve(
        Query(
            facts=_facts, pack=_pack,
            as_of_effective=str(_case["asOfEffective"]),
            as_of_knowledge=str(_case["asOfKnowledge"]),
            decision=str(_case["question"]),
            free="nc:noticeMailedDate",
            target={"kind": "boolean", "value": True},
        ),
        REGISTRY,
    )
    print("\n  NO CONTRADICTION RAISED — the guard did not fire, which is a bug.")
except SolverKernelContradiction as exc:
    print()
    for line in str(exc).splitlines():
        print(f"  {line}")
finally:
    query_module._encode = _real_encode

print()
print("=" * 72)
print("""
Every value above was run through duly_kernel.api.adjudicate on a
reconstructed, content-re-addressed fact set. No solver output reached a
receipt, and no decision changed. The two verdicts are not equally strong:
SATISFIABLE is checked pointwise, UNSATISFIABLE rests on the encoding.

    spec/whatif.md            the contract, the fragment, and the boundaries
    spec/pack-verification.md the SMT encoding this reuses, unextended
""".strip())
