"""What-if queries: solving a rule pack backwards.

`prove` asks a question about the *rulebase* ("can these two rules both
fire?"). A receipt answers a question about a *run* ("what was decided, and
why?"). This package answers a third kind of question, which is neither:
**what would have to be true for the decision to come out differently?**

    Given this case, this pack and this evaluation point, free exactly one
    input and ask which of its values produce a target decision — plus the
    extremal one: the latest compliant mailing date, the largest fee that
    owes no cure, the earliest date funds may be disbursed.

The answer is a *proposal about a hypothetical run*, and a proposal is not a
finding. So nothing here is believed on the solver's word:

- **The solver proposes, the kernel disposes.** Every value returned has been
  run through `duly_kernel.api.adjudicate` on the reconstructed fact set, and
  the resulting decision compared against the target. An unverified value is
  never returned.
- **Extremal answers are boundary-verified**: the extremal value produces the
  target *and* one step beyond it does not.
- **A solver/kernel disagreement is a loud error** carrying both artifacts
  (`SolverKernelContradiction`), never a silently dropped answer.

Read `spec/whatif.md` for the contract, the fragment, and the deliberate
boundaries. The one asymmetry to carry away, because it is the difference
between the two answers this tool gives:

    A SATISFIABLE answer is pointwise-verified — the kernel ran and agreed.
    An UNSATISFIABLE answer is not, because there is no single point to
    check. "No value works" rests on the encoding's faithfulness alone,
    which is a strictly weaker claim.

Nothing here reaches a receipt. Like `prove`, this is an analysis tool that
sits beside adjudication rather than inside it, and z3-solver stays an
optional dependency.
"""

from .query import (
    SATISFIABLE,
    UNSATISFIABLE,
    UNSUPPORTED,
    Answer,
    Query,
    SolverKernelContradiction,
    Unsupported,
    WhatIfReport,
    solve,
)

__all__ = [
    "Answer",
    "Query",
    "SolverKernelContradiction",
    "Unsupported",
    "WhatIfReport",
    "solve",
    "SATISFIABLE",
    "UNSATISFIABLE",
    "UNSUPPORTED",
]
