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

## 9. The review arc

Pick **NY nonrenewal — review arc (low-confidence extraction)**. Same two documents, but this time the extraction "read" the mailing date badly: the fact carries confidence **0.62**, below the **0.9** floor the notice pack (2026.3.0) sets for that attribute. This scenario walks the M3 loop end to end: abstain → review → correct → flip → regression case.

Before you start, note the small line under the document list in the left pane: it names which extractor produced the rendition and says the facts were served from the session fact store. At demo startup the extraction pipeline ran over the committed starter PDFs — the Docling adapter when the `extraction` extra is installed, the honest scripted stub otherwise — and each run's envelope was verified before its facts were ingested.

### 9a. The abstention

Ask *"Was this termination notice compliant?"* The verdict is an amber **Compliant** — *"Presumption only — noticeMailedDate excluded at confidence 0.62, below the 0.9 floor."* The kernel did not use the shaky date; it fell back to the default presumption and the receipt says so. In the audit pane, a new **Abstentions** section shows the entry: the reason (`Low confidence`), the score against the floor, where the floor came from (pack + version, attribute override vs. default), and the excluded fact itself — click it and the document pane still jumps to *"Date of Mailing: July 25, 2026"*, because an excluded fact is still a grounded fact.

### 9b. Correct it

Click **Review & correct**. The inline form is prefilled with the machine's value — the extraction read the right date, it was just not confident enough. Confirm the value (or type a different one), add your name and role, and apply. The correction becomes a first-class human-asserted GroundedFact that **supersedes** the below-floor machine fact, is validated and ingested through the review queue (`duly_review`), and the decision re-adjudicates on the spot: the verdict flips to red **Not compliant** (38 days notice given, 45 required), the abstention section disappears, and the derivation now cites the human fact with its actor — look for the `human · reviewer:… (role)` line on the fact chip. The status pill notes the transition. Corrections live in this server process only and reset on restart.

### 9c. Export the regression case

A **Corrections applied** panel now records the resolution. **Export as golden case** downloads a zip in the golden corpus layout — `cases/review-NNNN/` with `case.yaml` and the post-correction fact set (a store projection at the resolution's knowledge time), plus `receipts/review-NNNN.json`, freshly adjudicated. Unzip it into `golden/` and `uv run python -m duly_assurance verify` replays it byte-for-byte. The demo never writes into the repository itself; committing the case is deliberately a human act. One resolved item also yields one labeled calibration pair — the panel says how to export such labels (`python -m duly_review pairs`) and points at the calibration module, with the censored-sample caveat attached.

The committed [review-0001](../golden/cases/review-0001) golden case is this exact arc, frozen at the API level.

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
