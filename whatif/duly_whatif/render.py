"""Rendering a what-if report, text and JSON.

One rule governs the wording, and it is the reason this module exists rather
than a couple of print statements: **the two verdicts this tool returns are
not equally strong, and the output has to say so where a user will read it.**

A SATISFIABLE answer was run through the kernel — the value is a value the
kernel actually decided on. An UNSATISFIABLE answer was not, because "no
value works" has no single point to check; it rests on the encoding's
faithfulness alone. Burying that in the spec and printing two verdicts that
look alike would be the dishonest option, so UNSATISFIABLE prints its own
caveat every time.
"""

from __future__ import annotations

import json

from .query import SATISFIABLE, UNSATISFIABLE, WhatIfReport

__all__ = ["render", "report_json", "UNSAT_CAVEAT"]


UNSAT_CAVEAT = (
    "This verdict is WEAKER than a satisfying one, and the difference is not a "
    "formality.\n"
    "  A satisfying answer is checked pointwise: the kernel is handed the "
    "proposed case and\n"
    "  agrees. \"No value works\" has no point to check, so nothing here was "
    "verified against\n"
    "  the kernel — it rests entirely on the SMT encoding being a faithful "
    "reading of the pack.\n"
    "  Treat it as a strong hint to look, not as a proof that there is nothing "
    "to find."
)

_MAXIMALITY = (
    "The extremal value and the step beyond it were both run through the "
    "kernel. That\n"
    "  nothing FURTHER out reaches the target is the one part the kernel "
    "cannot confirm\n"
    "  pointwise; it rests on the encoding, like every other UNSAT claim here."
)


def render(report: WhatIfReport, *, verbose: bool = False) -> str:
    lines: list[str] = []
    lines.append(f"pack {report.pack} {report.pack_version}")
    lines.append(f"  decision   {report.decision}")
    lines.append(f"  as of      {report.as_of_effective}")
    lines.append(f"  today      {report.current}")
    freed = "the evaluation point" if report.free == "asOf" else report.free
    lines.append(f"  freed      {freed}  ({report.free_kind})")
    lines.append(f"  target     {report.target}")
    lines.append("")

    if report.verdict == SATISFIABLE:
        lines.extend(_satisfiable(report))
    elif report.verdict == UNSATISFIABLE:
        lines.append(f"  {UNSATISFIABLE}")
        lines.append(f"    {report.reason}")
        lines.append("")
        if report.complete:
            # A finite domain is the one case where "no value works" IS
            # pointwise verified: every member was run.
            lines.append("    Every value was checked against the kernel individually,")
            lines.append("    so this exhausts the domain rather than relying on the encoding.")
        else:
            for line in UNSAT_CAVEAT.splitlines():
                lines.append(f"    {line}")
    else:
        lines.append(f"  {report.verdict}")
        lines.append(f"    {report.reason}")

    if report.notes:
        lines.append("")
        lines.append("  notes:")
        for note in report.notes:
            lines.append(f"    - {note}")
    if verbose and report.assumptions:
        lines.append("")
        lines.append("  domain assumptions:")
        for a in report.assumptions:
            lines.append(f"    - {a}")
    return "\n".join(lines)


def _satisfiable(report: WhatIfReport) -> list[str]:
    lines = [f"  {SATISFIABLE}"]
    if report.unbounded and report.extremal is None:
        lines.append(f"    {report.reason}")
        return lines

    if report.extremal is not None:
        label = {
            "max": "largest", "min": "smallest", "nearest": "nearest",
            "any": "witness (every value works)",
        }.get(report.extremal_direction or "", "extremal")
        lines.append(
            f"    {label} value reaching the target: {report.extremal.value}"
        )
        lines.append(
            f"      kernel confirms  {report.extremal.value} -> "
            f"{report.extremal.decision}"
        )
        if report.boundary is not None and report.boundary.refuted:
            lines.append(
                f"      kernel refutes   {report.boundary.value} -> "
                f"{report.boundary.decision}"
            )
        elif report.boundary is not None:
            lines.append(f"      boundary not checked: {report.boundary.note}")
        lines.append("")
        for line in _MAXIMALITY.splitlines():
            lines.append(f"    {line}")
        return lines

    lines.append(f"    values reaching the target ({len(report.answers)}):")
    for answer in report.answers:
        lines.append(f"      {answer.value}  ->  {answer.decision}")
        if answer.note:
            lines.append(f"        ({answer.note}: {answer.representative})")
    return lines


def report_json(report: WhatIfReport) -> str:
    payload = {
        "pack": report.pack,
        "packVersion": report.pack_version,
        "decision": report.decision,
        "asOfEffective": report.as_of_effective,
        "currentDecision": report.current,
        "freed": report.free,
        "freedKind": report.free_kind,
        "target": report.target,
        "verdict": report.verdict,
        "reason": report.reason,
        "complete": report.complete,
        "unbounded": report.unbounded,
        "extremalDirection": report.extremal_direction,
        "extremal": _answer_json(report.extremal),
        "answers": [_answer_json(a) for a in report.answers],
        "boundary": (
            None if report.boundary is None else {
                "value": report.boundary.value,
                "decision": report.boundary.decision,
                "refutedByKernel": report.boundary.refuted,
                "note": report.boundary.note,
            }
        ),
        "notes": report.notes,
        "assumptions": report.assumptions,
        "unsatIsWeaker": (
            None if report.verdict != UNSATISFIABLE
            else not report.complete
        ),
    }
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)


def _answer_json(answer) -> dict | None:
    if answer is None:
        return None
    return {
        "value": answer.value,
        "factValue": answer.fact_value,
        "decision": answer.decision,
        "verifiedByKernel": answer.verified,
        "representative": answer.representative,
        "note": answer.note,
    }
