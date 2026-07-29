# Demo tour

A guided walkthrough of the duly demonstration. Take it in order — it builds from "read a document" to the effective-dated replay that is the project's core claim.

> Maintenance note: this tour is part of the demo. If a change alters what a step shows (new buttons, new scenarios, different verdict text), update the corresponding step in the same PR.

## Start the demo

```bash
uv sync
uv run uvicorn demo.app:app --port 8788
```

Open http://localhost:8788.

## 1. Start with the insurance scenario

The scenario picker (top right) defaults to **New York homeowners nonrenewal notice timing**. The left pane shows the case's two documents as tabs — the Declarations Page and the Notice of Nonrenewal. Flip between them and note the yellow highlights: those are the exact phrases facts were extracted from. Nothing else is highlighted because nothing else was used.

## 2. Ask the question

Click the question chip: *"Was this termination notice compliant?"* You get the verdict — **Not compliant** — with a plain-English sentence (38 days notice given, 45 required) and a **LIVE** badge. The badge means the kernel adjudicated this request just now; it is not a canned response. (An amber **fixture** badge would mean the demo fell back to a pre-committed receipt.)

## 3. Read the reasoning like a proof

The right pane shows the derivation tree. Note its shape: the conclusion (`noticeCompliant = false`, rule NC-NR-01) sits on top, with a *sub-conclusion* nested inside — `requiredMinimumNoticeDays = 45`, from rule NY-NR-45 — because the deficiency rule needed the minimum established before it could compare. That two-level structure is the defeasible rulebase at work.

## 4. Click a fact chip

Click any fact in the tree (say, the mailing date). The document pane switches to the right tab, scrolls to the source sentence, and flashes it. Every step of reasoning traces to ink on a page — the "answer plus receipt" thesis in one interaction.

## 5. Read the rules-fired cards

Below the tree, each fired rule shows its citation (a link to the actual statute text), version, priority, and effective window. On NC-NR-01, note the red **defeated: NC-DEF-00** badge: the default presumption of compliance was overridden, and the receipt says so explicitly.

## 6. The flip

Change the **As of** date (top right) to a date in 2025 — say `12/15/2025`. The verdict turns green **Compliant**, and the rules pane now shows `NY-NR-45-LEGACY` — the older 30-day minimum with its bounded effective window — alongside the surviving default presumption. Same documents, same facts, different date, opposite lawful answer, both fully receipted. Flip back and it turns red again.

(The pre-2026 30-day rule is marked `DEMO-SYNTHETIC` in the pack: it exists to demonstrate effective-dated replay and is not real statutory history.)

## 7. Download the artifacts

Three buttons at bottom right:

- **Receipt (JSON)** — the machine-verifiable, content-hashed decision record.
- **Audit report (Markdown / PDF)** — the examiner-facing document: conclusion, reasoning narrative with quoted evidence, cited rules, and a technical appendix with every hash and the exact replay command. Download it at both as-of dates and compare. See a committed [example report](example-audit-report.md).

## 8. Switch domains

Pick **TRID transfer-tax tolerance** in the scenario picker. Same machinery, different domain: a Loan Estimate and Closing Disclosure, the question *"Does this fee increase require a tolerance cure?"*, and the answer **250.00 USD** — computed as actual minus disclosed after the transfer tax is classified zero-tolerance under the cited CFR section. Nothing about the UI changed; only the rule pack and facts did. That is the bring-your-own-domain argument made visible.

## Behind the curtain: the CLI

The same adjudication with no UI at all:

```bash
uv run python -m duly_kernel \
  --facts starters/notice-ny/facts \
  --pack rulepacks/termination-notice-us-states/pack.yaml \
  --asof 2026-07-25 \
  --question nc:noticeCompliant
```

Run it twice and diff the output — byte-identical. That is the determinism claim, verifiable yourself. Add `--report tour.md --report-pdf tour.pdf` to render the audit report from the command line, or `--asof 2025-12-15` to reproduce the flip.
