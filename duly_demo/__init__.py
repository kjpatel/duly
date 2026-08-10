"""The duly demonstration workspace: four surfaces over one kernel.

- the decision workspace (``duly_demo.app``) — ask a question of a document
  and read the receipt that answers it,
- the rule studio (``duly_demo.rules_api``) — browse, edit and prove packs,
- the evidence browser (``duly_demo.evidence_api``) — the case's facts as
  objects, at a knowledge time you choose,
- the receipt viewer (``duly_demo.receipts_api``) — open a receipt that
  already exists and check whether it holds.

All four are **toolkit, not teaching content**: they read whatever packs,
scenarios, cases and receipts the deployment's content root offers (see
``duly_demo.content``), and report an honest emptiness when it offers none.

Run the whole demonstration with::

    uvicorn duly_demo.app:app --port 8788

FastAPI is an optional dependency of the wheel (the ``demo`` extra), and the
check below is here rather than in each of the four modules because this is
the one file all four pass through. It raises rather than degrading, which is
the opposite of what every *surface* in this package does — deliberately: the
surfaces degrade when the kernel or the store is missing because there is
still a page to serve and an honest emptiness to report, and there is no such
thing here. Without FastAPI the package has no importable surface at all, so
the honest answer is one actionable failure at the door instead of four
identical ``ModuleNotFoundError``\\ s deeper in.
"""

try:  # pragma: no cover - the repo's dev group always has it
    import fastapi as _fastapi  # noqa: F401
except ImportError as exc:  # pragma: no cover - proved by the wheel smoke job
    raise ImportError(
        "duly_demo needs FastAPI, which duly does not install by default.\n"
        "It is behind the `demo` extra, which also covers duly_review's HTTP\n"
        "surface:\n"
        "    pip install 'duly[demo]'\n"
        "Add the `report` extra too for the PDF audit report: 'duly[demo,report]'."
    ) from exc

del _fastapi
