# Demo tour

A guided walkthrough of the duly demonstration. Take it in order — it builds from "read a document" to the effective-dated replay that is the project's core claim.

> Maintenance note: this tour is part of the demo. If a change alters what a step shows (new buttons, new scenarios, different verdict text), update the corresponding step in the same PR.

## Start the demo

A hosted instance runs at **<https://duly.nyxworks.ai/>** with the same code and
the same seven scenarios, and steps 1–8 and 11–12 work there as written — they
only read.

**Steps 9 and 10 want a local server.** Both write to state the demo process
shares across every visitor: the review arc ingests your correction into the
in-memory fact store, and the rule studio's drafts are process-global, not
per-browser. On the hosted instance you would be editing what the next visitor
sees, and a restart discards it. Run those two here:

```bash
uv sync
uv run uvicorn duly_demo.app:app --port 8788
```

Open <https://duly.nyxworks.ai/> or http://localhost:8788.

Each of the four pages opens with a three-step orientation strip under its title — what to click, in what order. Dismiss it with **Got it** and the choice is remembered per page; **Show guide** under the page title brings it back. The strip is the short version of this tour, and the two are kept in step by hand: if a change moves what a page's first three actions are, the strip's copy in [duly_demo/static/guide.js](../duly_demo/static/guide.js) is part of that change. `duly_demo/tests/test_guide.py` enforces that every page has one and that no guide is orphaned, but it cannot tell you the words went stale.

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

Every verdict this tour quotes holds on whatever day you read it, because each scenario opens at a date it *declares* — `defaultAsOf` in its `scenario.json`, here the day the notice was mailed — rather than at today's. That was not always true: the date used to fall back to the wall clock, so a tour written on Tuesday described a demo that could answer differently on Friday.

## 7. Download the artifacts

Four buttons at bottom right:

- **Receipt + facts** — the receipt *and* the fact set it was adjudicated over, wrapped in one JSON array. This is the export that still replays somewhere the facts are not on disk, which is every artifact that leaves the machine that produced it; drop the whole file into the receipt viewer's paste box in step 12 and all three checks run.
- **Receipt (JSON)** — the machine-verifiable, content-hashed decision record, and the smaller claim: it proves what was decided and permanently pins *which* evidence was used, without carrying — or disclosing — the evidence itself.
- **Audit report (Markdown / PDF)** — the examiner-facing document: conclusion, reasoning narrative with quoted evidence, cited rules, and a technical appendix with every hash and the exact replay command. Download it at both as-of dates and compare. See a committed [example report](example-audit-report.md).

## 8. Switch domains

Pick **TRID transfer-tax tolerance** in the scenario picker. Same machinery, different domain: a Loan Estimate and Closing Disclosure, the question *"Does this fee increase require a tolerance cure?"*, and the answer **250.00 USD** — computed as actual minus disclosed after the transfer tax is classified zero-tolerance under the cited CFR section. Nothing about the UI changed; only the rule pack and facts did. That is the bring-your-own-domain argument made visible.

## 9. The review arc

Pick **NY nonrenewal — review arc (low-confidence extraction)**. Same two documents, but this time the extraction "read" the mailing date badly: the fact carries confidence **0.62**, below the **0.9** floor the notice pack (2026.3.0) sets for that attribute. This scenario walks the M3 loop end to end: abstain → review → correct → flip → regression case.

Before you start, note the small line under the document list in the left pane: it names which extractor produced the rendition and says the facts were served from the session fact store. At demo startup the extraction pipeline ran over the committed starter PDFs — the Docling adapter when the `extraction` extra is installed, the honest scripted stub otherwise — and each run's envelope was verified before its facts were ingested.

### 9a. The abstention

Ask *"Was this termination notice compliant?"* The verdict is an amber **Compliant** — *"Presumption only — noticeMailedDate excluded at confidence 0.62, below the 0.9 floor."* The kernel did not use the shaky date; it fell back to the default presumption and the receipt says so. The audit pane's **Abstentions** tab — its label now reads `Abstentions · 1` — shows the entry: the reason (`Low confidence`), the score against the floor, where the floor came from (pack + version, attribute override vs. default), and the excluded fact itself — click it and the document pane still jumps to *"Date of Mailing: July 25, 2026"*, because an excluded fact is still a grounded fact.

The **Derivation** tab carries a matching **Input excluded** card naming the rule that went unevaluated for want of that fact, with a button through to the abstention itself. It is a pointer rather than a second telling — the score, the floor's provenance and the correction form live in one place — and it sits *after* the tree rather than inside it, because the tree is the receipt's own derivation and a synthetic node within it would be the page inventing a step the kernel never took.

Ask the LA County scenario's SB 2 fee question to see the other half. The same case still carries the same exclusion, and the receipt is byte-identical in that respect, but no rule behind *that* answer reads the attribute: the tab reads `Abstentions · none`, the derivation shows no gap, and the exclusion folds under one line. Relevance is decided once, by `duly_kernel.relevance`, so this pane and the audit report a regulator reads cannot disagree about it.

### 9b. Correct it

Click **Review & correct**. The inline form is prefilled with the machine's value — the extraction read the right date, it was just not confident enough. Confirm the value (or type a different one), add your name and role, and apply. The correction becomes a first-class human-asserted GroundedFact that **supersedes** the below-floor machine fact, is validated and ingested through the review queue (`duly_review`), and the decision re-adjudicates on the spot: the verdict flips to red **Not compliant** (38 days notice given, 45 required), the abstention section disappears, and the derivation now cites the human fact with its actor — look for the `human · reviewer:… (role)` line on the fact chip. The status pill notes the transition. Corrections live in this server process only and reset on restart.

### 9c. Export the regression case

A **Corrections applied** panel now records the resolution. **Export as golden case** downloads a zip in the golden corpus layout — `cases/review-NNNN/` with `case.yaml` and the post-correction fact set (a store projection at the resolution's knowledge time), plus `receipts/review-NNNN.json`, freshly adjudicated. Unzip it into `examples/golden/` and `uv run python -m duly_assurance verify` replays it byte-for-byte. The demo never writes into the repository itself; committing the case is deliberately a human act. One resolved item also yields one labeled calibration pair — the panel says how to export such labels (`python -m duly_review pairs`) and points at the calibration module, with the censored-sample caveat attached.

The committed [review-0001](../examples/golden/cases/review-0001) golden case is this exact arc, frozen at the API level.

## 10. The rule studio

Everything so far asked *what did the rules decide about this document*. Click **Rule studio** in the header (or open <http://localhost:8788/rules>) to ask the two questions that come next: *what do the rules say*, and *what happens if I change them*. This step edits a draft the demo process holds globally, so run it on your own server rather than the hosted one — reading the grids is safe anywhere, but the edit below is not yours alone.

The left rail lists the six packs discovered under `examples/rulepacks/`, each with its rule count, how many outcomes it declares, and how many committed golden receipts cite it. Pick **termination-notice-us-states** — 226 of the 351 golden receipts are its.

### 10a. Read the rules as a decision table

The centre pane opens on **Decision tables**: one grid per attribute the pack concludes, rows are rules, columns are the inputs they bind. `nc:requiredMinimumNoticeDays` is the readable one — seven rules, three inputs, and the whole state-by-state minimum-notice policy visible at once. Note three things the grid is careful about:

- An empty cell is not one thing but two. *`any`* means the rule binds that input and does not constrain it — the fact must exist for the rule to fire, it is just not tested. *`—`* means the rule does not bind it at all. That is [the DMN `-` cell](../spec/dmn.md) and it is the distinction authors trip on, because it silently changes which cases a rule reaches.
- `NC-NR-01`'s guard, `days_between(mailed, expiration) < minDays`, relates three bindings, so no column owns it. It gets its own **cross-input** row. A DMN table could not put it in a cell either; the grid says so rather than picking a column.
- `NY-NR-45` and `NY-NR-45-LEGACY` sit at the same priority with identical cells. They are separated only by the **In force** column — the effective-dated replay from step 6, seen from the rules' side.

This grid is a *view of the rule IR*, not a DMN document: `duly_dmn` compiles DMN into the IR and deliberately does not decompile. Authoring *through* DMN is §10d.

### 10b. Change a rule, and find out what you did

Click into `NY-NR-45`'s conclusion cell and change `45` to `60`. The **Rules** tab has the same edit as a form (with citation, version, effective window and bindings); the **pack.yaml** tab has it as text. Whichever you use, the right-hand **Verify** rail is the point:

- **Validation** re-runs the kernel's own `validate_pack` on every keystroke-commit. An invalid draft is kept and reported, not discarded — an author mid-edit has an invalid pack most of the time.
- **Declared cases** runs the pack's `expected.yaml` — the same assertions `examples/tests/test_rulepacks.py` makes. All four still pass.
- **Try a case** adjudicates one case by hand: pick a fact set, change an input value, watch the verdict, the rules fired and the defeat chain move. It also tells you whether your draft changed *this* case relative to the committed pack.
- **Golden impact** re-adjudicates all 351 committed cases with your draft swapped in: **1 of 351 decisions flip**, `notice-ny-0048`, true → false.
- **Static verification** (needs `uv sync --extra prove`) proves the same-priority rules disjoint, names the input regions no rule covers, and — the one that matters while editing — proves whether your draft and the committed pack decide alike. They do not, and it hands you the exact input where they part: `governingState = "US-NY"`, `noticeType = "Nonrenewal"`, committed 45, draft 60.

Stop on the two lines that disagree. **Every declared case passes, and the corpus flips a decision.** That is not a bug in either; they answer different questions. `expected.yaml` catches a pack that *breaks*; only the corpus catches a pack whose *meaning moved*. Both are wired into CI for exactly that reason, and the studio is the first place you can watch them disagree.

### 10c. Read the diff, then commit it yourself

The **Diff** section shows the change twice. The first diff normalises both sides through the pack emitter, so a one-value edit is a two-line diff. The second — behind *Show the file diff* — is what `git` would see, and for a structured edit that includes every YAML comment the re-emission drops. The comments in these packs are not decoration (`DEMO-SYNTHETIC`, `TODO(verify)`, the `MODELING BOUNDARY` header in the TILA pack), so their loss is shown rather than hidden. Editing on the **pack.yaml** tab is the lossless path.

**Export** downloads `pack.yaml`, or a `rulepacks/<name>/` bundle with an `expected.yaml` skeleton and a NEXT-STEPS note. The studio never writes into `examples/rulepacks/` — same rule as the golden-case export in step 9c, for the same reason: committing an artifact into the repository is a human act, made through a diff a human read.

### 10d. Compile a decision table

The **DMN import** tab takes a DMN 1.3+ document and compiles it into a rule pack. Load the committed `trid-fee-tolerance` example: three rules across two decisions, validated by the kernel's pack validator before it comes back, and **Adopt** turns it into a draft that browses and tests exactly like a hand-written pack.

Then click one of the red examples. Each is a minimal document that breaks one way — an uncited row, an unsupported hit policy, a non-S-FEEL cell — and each refusal names the decision, the row and the cell. A compiler that refuses is only trustworthy once you have watched it refuse.

### 10e. Start a pack from nothing

**New pack** drafts a skeleton that already obeys the conventions new packs most often miss: an `idPrefix`, a convention-shaped rule id, an explicit `TODO(verify)` where the citation belongs, and decision phrasing so a non-boolean answer never renders as a raw CURIE. Its Verify rail is honest about what it cannot yet do — no declared cases, and no golden case exercises it, so impact analysis literally cannot see it. That is the "0 of 351 decisions flip, forever" trap from [examples/rulepacks/README.md](../examples/rulepacks/README.md), said out loud before you fall into it.

## 11. The evidence browser

The workspace showed you the facts *this question's receipt cited*. That is the right frame for reading a decision and the wrong one for reading a case: it never shows a fact no rule needed, and it cannot show a fact that is no longer true. Click **Evidence browser** in the header (or open [`/evidence`](https://duly.nyxworks.ai/evidence)) for the other frame — every document the case holds and every fact ever asserted about it.

Pick **NY nonrenewal — review arc**, the same case you corrected in step 9.

### 11a. The document has two faces

The centre pane offers **Rendition** and **Source PDF**, and the distinction is not cosmetic. A fact's grounding cites a `documentSha256` — the bytes — and a `charSpan` into a *rendition*, which is one extractor's reading of those bytes. The rendition tab draws the spans; the source tab serves the committed PDF and reports whether the file on disk still hashes to what the facts cite.

The source tab has no highlights, and that is deliberate: character offsets are not page coordinates, and no fact carries the latter. A highlight drawn on the PDF would be a guess wearing the costume of provenance. Where two facts quote overlapping text — the TRID Closing Disclosure does — the browser says which span it could not draw rather than dropping it silently.

### 11b. Everything the receipt view left out

Click any highlight, or any fact in the left rail. The inspector shows the full record: the grounding (document, page, span, source hash, which extractor's rendition), the provenance (machine extractor and run, or the named human who asserted it), the confidence *with its method and calibration reference*, the content hash, and the ontology.

That last panel is the conformance gate — the same one CI runs over every committed fact — narrowed to this one: the ontology its `schemaRef` pins, the class the attribute is declared on, its value kind, and for coded values the permitted code set. **Cited by** at the bottom names every question this case's pack asks and this fact's role in each: cited in the derivation, abstained on, or not in the derivation at all. That third answer is a real distinction — a live fact read by a rule that did not survive is not cited — and the panel says so rather than leaving a blank. Each question links back to the workspace at *that* question of *that* case, closing the loop the tour opened with: the workspace shows you one answer's evidence, this shows you one piece of evidence's answers.

### 11c. Drag the dial

This is the step the whole surface exists for. The strip under the toolbar is a **knowledge time** dial, and its stops are the moments this case's knowledge actually changed — not a free date field, because every date in between projects identically.

At the last stop you see the case as it stands: four live facts and one superseded. Drag back one stop, to before you applied the correction, and the case rearranges. The reviewer's fact becomes **not yet known**. The below-floor machine fact — `noticeMailedDate = 2026-07-25`, struck through a moment ago — is **live** again, and its inspector says a later fact supersedes it, drag forward to see. The history panel keeps the whole chain, marking the events this horizon has not reached rather than hiding them, because the audit trail is not the projection.

Drag to the first stop and three facts have not been extracted yet.

The store has been bitemporal since M2 and every receipt has carried a knowledge time; this is where that stops being a field in a JSON document. It is also why corrections are modelled as supersession rather than mutation: an edit in place would have nothing to show here, because there would be nothing left of what was believed before.

### 11d. What it will not do

Without the session fact store — fixture mode, or a checkout where the extraction pipeline cannot run — there is no event log. The browser then serves the committed facts, all live, and says the timeline is *absent* rather than showing an empty one that implies knowledge never changed. A retracted fact with no replacement is not reachable from any live fact through the store's public API, so it does not appear; nothing in the demo retracts, and reaching around the API for it would be worse than the gap.

Deep links carry the whole view — `?case=&fact=&k=&tab=` — because "look at this fact, as of before the correction" is only a useful sentence if it can be a URL. The workspace takes `?scenario=&question=` for the same reason, which is what the **Cited by** links use; an unknown scenario or question falls back to the default rather than erroring, so a stale link still lands somewhere usable.

## 12. The receipt viewer

The workspace produces a receipt. This surface reads one back. Click **Receipt viewer** in the header (or open [`/receipt`](https://duly.nyxworks.ai/receipt)) — the question it answers is the one an auditor actually arrives with: *someone handed me this receipt; does it hold?*

The toolbar holds the whole committed corpus behind a search field: filter by rule pack, then type a case id or a receipt hash — arrow keys and Enter, or click. 351 receipts are searched rather than browsed, so the picker sits across the top and the width goes to the two panes that need it. Type `notice-ny-0001`. Three things happen at once, and the third is the point.

### 12a. The report is the kernel's, in a third medium

The centre pane is the same audit report you downloaded in step 7 — conclusion, reasoning with quoted evidence, rules applied, evidence, integrity — rendered as HTML rather than Markdown or PDF. Not a re-implementation: `duly_kernel.report` builds one list of typed sections and three renderers walk it. A new medium is a new walk, which is what keeps the browser and the PDF from drifting into two accounts of one decision. The **Receipt JSON** tab is the bytes themselves.

### 12b. Verification runs on open, not on request

The right rail ran three checks before the report appeared, and reports them separately because they fail for different reasons:

- **Receipt hash** — recompute SHA-256 over the receipt's canonical body and compare it to the `receiptSha256` it carries. This needs nothing but the receipt, which is why a receipt from outside this repository is still worth opening.
- **Input facts** — every fact the receipt pinned is present, and each one hashes to the content hash in its own id.
- **Replay** — re-run `duly_kernel.api.adjudicate` over those facts, that pack version and the receipt's own asOf pair, and compare byte-for-byte. This is `python -m duly_assurance verify` narrowed to one receipt.

Now **Paste a receipt**, drop in `examples/golden/receipts/notice-ny-0001.json`, and edit one character of the verdict before verifying. The hash check fails: the document has been altered. That is the easy forgery.

The instructive one takes a second step. Flip the verdict *and* recompute `receiptSha256` so the document is internally consistent again, paste it with the genuine facts from `examples/golden/cases/notice-ny-0001/facts/`, and watch what happens: **receipt hash passes, facts pass, replay fails.** The report reads "Compliant" in full sentences with real citations and real quoted evidence, and it is a lie — because the rules, run again, do not produce it. A hash proves a document has not changed since someone sealed it. Only re-running the rules proves the seal was ever honest. That gap is the whole reason verification is three checks and not one.

### 12c. What it refuses to guess

Paste a receipt with no facts alongside it. The hash still verifies; the evidence and replay checks report **not checked** and say why — a receipt pins its facts by content hash, so it genuinely cannot reproduce them, and a viewer that quietly rendered a thinner report would be claiming completeness it does not have. **Rendered against** at the bottom of the rail always names what the report was built from.

*Not checked* is an absent input, not a refuted check, and the difference is worth feeling rather than reading: open a corpus case, download **Receipt + facts**, and paste that single file. The same three checks now pass, because the bundle carried the evidence the bare receipt could only name. Nothing about the receipt changed — it is byte-identical in both files — which is the point. Integrity travels inside the artifact; availability is a packaging decision somebody makes when the artifact leaves home.

The sharpest case is a pack whose version has moved since the receipt was written. The viewer does not fall back to whichever pack now declares that name: rule descriptions out of a different version would read as the text these rules carried, which they never did. It reports `pack-moved` with both versions and omits what it cannot source.

How it finds the pack at all is worth one line, because it is not the obvious thing. A receipt names its pack (`rulePack.name`) and that name is a *declaration inside the pack file*, not the directory the file sits in — nothing ties the two together, and duly's own packs agreeing is a coincidence of this repository. So the viewer reads every `rulepacks/*/pack.yaml` and matches on what each one declares. Rename a pack directory and every receipt still resolves.

One consequence worth knowing if you build on the API: `/api/receipts/inspect` takes raw JSON **text**, not objects. JavaScript has a single number type, so a fact's `"score": 1.0` survives a browser round trip as `1` — a different canonical body, a different content hash, and every genuine fact reported as tampered with. Content addressing is over bytes, so the bytes are what travel and Python does the only parse.

## Behind the curtain: the CLI

The same adjudication with no UI at all:

```bash
uv run python -m duly_kernel \
  --facts examples/starters/notice-ny/facts \
  --pack examples/rulepacks/termination-notice-us-states/pack.yaml \
  --asof 2026-07-25 \
  --question nc:noticeCompliant
```

Run it twice and diff the output — byte-identical. That is the determinism claim, verifiable yourself. Add `--report tour.md --report-pdf tour.pdf` to render the audit report from the command line, or `--asof 2025-12-15` to reproduce the flip.
