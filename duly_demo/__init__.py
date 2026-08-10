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
"""
