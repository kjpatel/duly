/* duly demo — vanilla JS, no dependencies.
 * All dynamic text is inserted via textContent / createTextNode; no innerHTML
 * with server data anywhere.
 */
"use strict";

const state = {
  scenarios: [],
  scenario: null,          // selected scenario summary from /api/scenarios
  documents: new Map(),    // docId -> {title, renditionText}
  activeDocId: null,
  activeAttribute: null,
  receipt: null,
  factIndex: {},
  engineMode: null,
  abstentions: [],         // enriched receipt abstention entries from the server
  review: null,            // review-queue state for the case (availability, resolved items)
  lastVerdictKey: null,
  requestSeq: 0,
};

const $ = (id) => document.getElementById(id);

/* ---------- formatting helpers ---------- */

function plural(count, singular, pluralForm = singular + "s") {
  return `${count} ${count === 1 ? singular : pluralForm}`;
}

function setWorkspaceStatus(text, mode = "ready") {
  const status = $("workspace-status");
  $("workspace-status-text").textContent = text;
  status.classList.toggle("loading", mode === "loading");
  status.classList.toggle("fixture", mode === "fixture");
  status.classList.toggle("error", mode === "error");
  status.classList.toggle("info", mode === "info");
}

function shortAttr(curie) {
  if (typeof curie !== "string") return "";
  const i = curie.indexOf(":");
  return i >= 0 ? curie.slice(i + 1) : curie;
}

function fmtValue(v) {
  if (v == null || typeof v !== "object") return String(v);
  switch (v.kind) {
    case "money": return `${v.amount} ${v.currency}`;
    case "boolean": return v.value ? "true" : "false";
    default: return String(v.value);
  }
}

function fmtDay(iso) {
  return typeof iso === "string" && iso.length >= 10 ? iso.slice(0, 10) : (iso || "");
}

function markId(factId) {
  return "mark-" + factId;
}

/* ---------- scenario loading ---------- */

async function init() {
  setWorkspaceStatus("Loading demo", "loading");
  const res = await fetch("/api/scenarios");
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  state.scenarios = await res.json();

  const select = $("scenario-select");
  select.replaceChildren();
  // One <optgroup> per domain, labels from the server (domainLabel), groups in
  // label order, scenarios in server order within each group.
  const groups = new Map();
  for (const sc of state.scenarios) {
    const label = sc.domainLabel || "Other";
    if (!groups.has(label)) groups.set(label, []);
    groups.get(label).push(sc);
  }
  for (const label of [...groups.keys()].sort((a, b) => a.localeCompare(b))) {
    const group = document.createElement("optgroup");
    group.label = label;
    for (const sc of groups.get(label)) {
      const opt = document.createElement("option");
      opt.value = sc.id;
      opt.textContent = sc.title;
      group.append(opt);
    }
    select.append(group);
  }
  select.addEventListener("change", () => selectScenario(select.value));
  $("asof-input").addEventListener("change", () => {
    if (state.scenario && state.activeAttribute) runAdjudication();
  });
  $("download-bundle").addEventListener("click", () => downloadReport("bundle"));
  $("download-receipt").addEventListener("click", () => downloadReport("receipt"));
  $("download-report-md").addEventListener("click", () => downloadReport("md"));
  $("download-report-pdf").addEventListener("click", () => downloadReport("pdf"));

  if (state.scenarios.length > 0) {
    // Deep link: ?scenario=&question=. The evidence browser links a fact's
    // citations back to the question that used it, and "look at the answer
    // this fact went into" is only a useful sentence if it carries a URL.
    // An unknown scenario or question falls back to the default rather than
    // erroring: a stale link should still land somewhere usable.
    const params = new URLSearchParams(window.location.search);
    const wanted = params.get("scenario");
    const start = state.scenarios.find((s) => s.id === wanted) || state.scenarios[0];
    select.value = start.id;
    await selectScenario(start.id, params.get("question"));
  } else {
    setWorkspaceStatus("No scenarios", "error");
  }
}

async function selectScenario(id, wantedAttribute = null) {
  const scenario = state.scenarios.find((s) => s.id === id);
  if (!scenario) return;
  setWorkspaceStatus("Loading scenario", "loading");
  $("workspace-eyebrow").textContent = scenario.domainLabel
    ? `Interactive adjudication demo · ${scenario.domainLabel}`
    : "Interactive adjudication demo";
  state.scenario = scenario;
  state.documents = new Map();
  state.activeDocId = null;
  state.receipt = null;
  state.factIndex = {};
  state.abstentions = [];
  state.review = null;
  state.lastVerdictKey = null;
  $("answer-card").classList.add("hidden");
  $("error-card").classList.add("hidden");
  $("derivation").replaceChildren();
  $("rules-fired").replaceChildren();
  renderAbstentions();
  renderCorrections();
  renderExtractionLabel();
  setDownloadsEnabled(false);

  $("asof-input").value = scenario.defaultAsOf || "";

  await Promise.all(scenario.documents.map(async (d) => {
    const res = await fetch(
      `/api/document/${encodeURIComponent(scenario.id)}/${encodeURIComponent(d.id)}`
    );
    state.documents.set(d.id, res.ok ? await res.json()
                                     : { title: d.title, renditionText: "" });
  }));

  renderDocumentList();
  if (scenario.documents.length > 0) activateDoc(scenario.documents[0].id);
  renderQuestions();

  if (scenario.questions.length > 0) {
    const wanted =
      wantedAttribute && scenario.questions.find((q) => q.attribute === wantedAttribute);
    state.activeAttribute = (wanted || scenario.questions[0]).attribute;
    highlightActiveQuestion();
    await runAdjudication();
  } else {
    setWorkspaceStatus("Scenario ready");
  }
}

/* ---------- document pane ---------- */

function documentFactCount(docId) {
  return Object.values(state.factIndex).filter((fact) => fact.documentId === docId).length;
}

function fileIcon() {
  const namespace = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(namespace, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", "17");
  svg.setAttribute("height", "17");
  svg.setAttribute("fill", "none");
  svg.setAttribute("aria-hidden", "true");

  const outline = document.createElementNS(namespace, "path");
  outline.setAttribute("d", "M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2Z");
  outline.setAttribute("stroke", "currentColor");
  outline.setAttribute("stroke-width", "2");
  outline.setAttribute("stroke-linejoin", "round");

  const detail = document.createElementNS(namespace, "path");
  detail.setAttribute("d", "M14 2v6h6M8 13h8M8 17h5");
  detail.setAttribute("stroke", "currentColor");
  detail.setAttribute("stroke-width", "2");
  detail.setAttribute("stroke-linecap", "round");

  svg.append(outline, detail);
  return svg;
}

function renderDocumentList() {
  const list = $("doc-tabs");
  list.replaceChildren();
  for (const d of state.scenario.documents) {
    const btn = document.createElement("button");
    btn.className = "document-option";
    btn.type = "button";
    btn.dataset.docId = d.id;
    btn.setAttribute("aria-pressed", "false");

    const icon = document.createElement("span");
    icon.className = "document-option-icon";
    icon.append(fileIcon());

    const copy = document.createElement("span");
    copy.className = "document-option-copy";
    const title = document.createElement("span");
    title.className = "document-option-title";
    title.textContent = d.title;
    const meta = document.createElement("span");
    meta.className = "document-option-meta";
    meta.textContent = plural(documentFactCount(d.id), "grounded fact");
    copy.append(title, meta);

    const arrow = document.createElement("span");
    arrow.className = "document-option-arrow";
    arrow.setAttribute("aria-hidden", "true");
    arrow.textContent = "→";

    btn.append(icon, copy, arrow);
    btn.addEventListener("click", () => activateDoc(d.id));
    list.append(btn);
  }
  $("source-count").textContent = plural(state.scenario.documents.length, "document");
}

function activateDoc(docId) {
  state.activeDocId = docId;
  for (const btn of $("doc-tabs").querySelectorAll(".document-option")) {
    const active = btn.dataset.docId === docId;
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-pressed", String(active));
  }
  renderDocument();
}

/* Build the highlighted rendition by slicing the text at span boundaries.
 * Never regex-replaces, never sets innerHTML from raw text. */
function renderDocument() {
  const container = $("doc-text");
  container.replaceChildren();
  const doc = state.documents.get(state.activeDocId);
  if (!doc) {
    $("document-title").textContent = "Select a document";
    $("doc-evidence-count").textContent = plural(0, "grounded fact");
    return;
  }
  $("document-title").textContent = doc.title || state.activeDocId;
  const text = doc.renditionText || "";

  const spans = [];
  for (const [factId, f] of Object.entries(state.factIndex)) {
    if (f.documentId !== state.activeDocId || !f.charSpan) continue;
    const { start, end } = f.charSpan;
    if (!Number.isInteger(start) || !Number.isInteger(end)) continue;
    if (start < 0 || end > text.length || end <= start) continue;
    spans.push({ start, end, factId, attribute: f.attribute });
  }
  spans.sort((a, b) => a.start - b.start || a.end - b.end);
  $("doc-evidence-count").textContent = plural(spans.length, "grounded fact");
  for (const btn of $("doc-tabs").querySelectorAll(".document-option")) {
    const meta = btn.querySelector(".document-option-meta");
    if (meta) {
      meta.textContent = plural(documentFactCount(btn.dataset.docId), "grounded fact");
    }
  }

  const frag = document.createDocumentFragment();
  let cursor = 0;
  for (const span of spans) {
    if (span.start < cursor) continue; // skip overlaps
    if (span.start > cursor) frag.append(document.createTextNode(text.slice(cursor, span.start)));
    const mark = document.createElement("mark");
    mark.id = markId(span.factId);
    mark.title = shortAttr(span.attribute);
    mark.textContent = text.slice(span.start, span.end);
    frag.append(mark);
    cursor = span.end;
  }
  if (cursor < text.length) frag.append(document.createTextNode(text.slice(cursor)));
  container.append(frag);
}

function focusFact(factId) {
  const f = state.factIndex[factId];
  if (!f || !f.documentId) return;
  if (state.activeDocId !== f.documentId) activateDoc(f.documentId);
  requestAnimationFrame(() => {
    const mark = document.getElementById(markId(factId));
    if (!mark) return;
    mark.scrollIntoView({ behavior: "smooth", block: "center" });
    mark.classList.remove("flash");
    void mark.offsetWidth; // restart the transition
    mark.classList.add("flash");
    setTimeout(() => mark.classList.remove("flash"), 1400);
  });
}

/* ---------- question / answer pane ---------- */

function renderQuestions() {
  const chips = $("question-chips");
  chips.replaceChildren();
  for (const q of state.scenario.questions) {
    const btn = document.createElement("button");
    btn.className = "chip";
    btn.type = "button";
    btn.textContent = q.question;
    btn.dataset.attribute = q.attribute;
    btn.addEventListener("click", () => {
      state.activeAttribute = q.attribute;
      highlightActiveQuestion();
      runAdjudication();
    });
    chips.append(btn);
  }
  $("question-count").textContent = plural(state.scenario.questions.length, "question");
}

function highlightActiveQuestion() {
  for (const btn of $("question-chips").querySelectorAll(".chip")) {
    const active = btn.dataset.attribute === state.activeAttribute;
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-pressed", String(active));
  }
}

/* How a decision reads is decided server-side and sent as `determination`, so
 * verdict wording lives in exactly one place. See _determination in duly_demo/app.py. */
const TONE_ICONS = { pos: "✓", neg: "×", warn: "!" };

async function runAdjudication() {
  const seq = ++state.requestSeq;
  setWorkspaceStatus("Evaluating", "loading");
  $("answer-card").classList.add("hidden");
  $("answer-card").setAttribute("aria-busy", "true");
  $("error-card").classList.add("hidden");
  const body = {
    scenarioId: state.scenario.id,
    attribute: state.activeAttribute,
    asOfEffective: $("asof-input").value || state.scenario.defaultAsOf,
  };
  let payload = null;
  let errorText = null;
  try {
    const res = await fetch("/api/adjudicate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (res.ok) {
      payload = await res.json();
    } else {
      let detail = `HTTP ${res.status}`;
      try {
        const err = await res.json();
        if (err && err.detail) detail = String(err.detail);
      } catch { /* keep status text */ }
      errorText = detail;
    }
  } catch (e) {
    errorText = String(e);
  }
  if (seq !== state.requestSeq) return; // a newer request superseded this one

  if (errorText !== null) {
    $("answer-card").removeAttribute("aria-busy");
    const card = $("error-card");
    card.textContent = errorText;
    card.classList.remove("hidden");
    // Drop the superseded receipt: a stale derivation beside "Evaluation failed"
    // reads as the audit trail for the question that just failed.
    state.receipt = null;
    state.factIndex = {};
    state.abstentions = [];
    state.review = null;
    $("derivation").replaceChildren();
    renderAbstentions();
    renderCorrections();
    renderRulesFired();
    renderDocument();
    setDownloadsEnabled(false);
    setWorkspaceStatus("Evaluation failed", "error");
    return;
  }
  $("error-card").classList.add("hidden");

  applyAdjudication(payload);
  const isFixture = payload.engineMode === "fixture";
  setWorkspaceStatus(
    isFixture ? "Fixture receipt" : "Decision ready",
    isFixture ? "fixture" : "ready"
  );
}

/* Apply one adjudication payload (from /api/adjudicate or /api/review/correct)
 * to the workspace. The caller owns the status pill. */
function applyAdjudication(payload) {
  state.receipt = payload.receipt;
  state.factIndex = payload.factIndex || {};
  state.engineMode = payload.engineMode;
  state.abstentions = payload.abstentions || [];
  state.review = payload.review || null;

  renderAnswer(payload);
  renderDerivation();
  renderAbstentions();
  renderCorrections();
  renderRulesFired();
  renderDocument(); // re-highlight with the (possibly new) fact index
  setDownloadsEnabled(true);
}

function setDownloadsEnabled(enabled) {
  for (const id of [
    "download-bundle",
    "download-receipt",
    "download-report-md",
    "download-report-pdf",
  ]) {
    $(id).disabled = !enabled;
  }
}

function renderAnswer(payload) {
  const card = $("answer-card");
  card.classList.remove("hidden");
  card.removeAttribute("aria-busy");

  const badge = $("engine-badge");
  badge.textContent = payload.engineMode === "live" ? "Computed" : "Fixture";
  badge.className = "badge " + (payload.engineMode === "live" ? "live" : "fixture");
  $("fixture-note").classList.toggle("hidden", payload.engineMode !== "fixture");

  const asOf = state.receipt && state.receipt.asOf;
  // Each half is its own nowrap span so a narrow footer wraps at the separator;
  // a bare string would break inside a date at its hyphens.
  const asofEl = $("answer-asof");
  asofEl.replaceChildren();
  if (asOf) {
    const effective = document.createElement("span");
    effective.textContent = `effective ${fmtDay(asOf.effective)} ·`;
    const knowledge = document.createElement("span");
    knowledge.textContent = `knowledge ${fmtDay(asOf.knowledge)}`;
    asofEl.append(effective, document.createTextNode(" "), knowledge);
  }

  const found = payload.determination || {};
  const tone = found.tone || "";
  card.classList.remove("pos", "neg", "warn");
  if (tone) card.classList.add(tone);
  $("determination-icon").textContent = TONE_ICONS[tone] || "→";

  const verdictEl = $("verdict");
  verdictEl.textContent = found.verdict || "";
  verdictEl.className = "verdict" + (tone ? " " + tone : "");
  // `detail` is stored unpunctuated so the server can compose it into a longer
  // sentence; it reads as a sentence on its own here.
  $("answer-text").textContent = found.detail ? `${found.detail}.` : "";

  const key = JSON.stringify(state.receipt && state.receipt.decision && state.receipt.decision.value);
  if (state.lastVerdictKey !== null && state.lastVerdictKey !== key) {
    card.classList.remove("pulse");
    void card.offsetWidth;
    card.classList.add("pulse");
    setTimeout(() => card.classList.remove("pulse"), 1000);
  }
  state.lastVerdictKey = key;
}

/* ---------- reasoning pane ---------- */

function factChip(factId) {
  const f = state.factIndex[factId];
  const btn = document.createElement("button");
  btn.className = "fact-chip";
  btn.type = "button";
  if (f) {
    const attr = document.createElement("span");
    attr.className = "fc-attr";
    attr.textContent = shortAttr(f.attribute);
    const val = document.createElement("span");
    val.className = "fc-value";
    val.textContent = " = " + fmtValue(f.value);
    btn.append(attr, val);
    if (f.quote) {
      const quote = document.createElement("span");
      quote.className = "fc-quote";
      quote.textContent = "“" + f.quote + "”";
      btn.append(quote);
    }
    if (f.provenance && f.provenance.label) {
      const prov = document.createElement("span");
      prov.className = "fc-prov" + (f.provenance.kind === "human" ? " human" : "");
      prov.textContent = f.provenance.kind + " · " + f.provenance.label;
      btn.append(prov);
    }
    btn.title = "Show in document";
    btn.addEventListener("click", () => focusFact(factId));
  } else {
    btn.textContent = factId;
    btn.disabled = true;
  }
  return btn;
}

function derivationNode(node) {
  const details = document.createElement("details");
  details.open = true;

  const summary = document.createElement("summary");
  const attr = document.createElement("span");
  attr.className = "node-attr";
  attr.textContent = shortAttr(node.conclusion && node.conclusion.attribute);
  const val = document.createElement("span");
  val.className = "node-value";
  val.textContent = "= " + fmtValue(node.conclusion && node.conclusion.value);
  summary.append(attr, val);
  if (node.rule) {
    const rule = document.createElement("span");
    rule.className = "node-rule";
    rule.textContent = node.rule;
    summary.append(rule);
  }
  details.append(summary);

  const premises = document.createElement("div");
  premises.className = "premises";
  for (const p of node.premises || []) {
    if (p && typeof p === "object" && "factId" in p) {
      premises.append(factChip(p.factId));
    } else if (p && typeof p === "object" && p.conclusion) {
      premises.append(derivationNode(p));
    }
  }
  if (premises.childNodes.length > 0) details.append(premises);
  return details;
}

function renderDerivation() {
  const container = $("derivation");
  container.replaceChildren();
  if (state.receipt && state.receipt.derivation) {
    container.append(derivationNode(state.receipt.derivation));
  }
}

/* ---------- extraction provenance ---------- */

function renderExtractionLabel() {
  const label = $("extraction-label");
  const extraction = state.scenario && state.scenario.extraction;
  const text = extraction && extraction.label ? extraction.label : "";
  const note = extraction && extraction.note ? " (" + extraction.note + ")" : "";
  label.textContent = text + note;
  label.classList.toggle("hidden", !text);
}

/* ---------- abstentions and the review flow ---------- */

/* Labels for the receipt's enumerated abstention reasons (vocabulary from the
 * decision-receipt schema, not verdict wording — that stays server-side). */
const REASON_LABELS = { low_confidence: "Low confidence", conflict: "Conflict" };

function renderAbstentions() {
  const container = $("abstentions");
  container.replaceChildren();
  const entries = state.abstentions || [];
  $("abstentions-title").style.display = entries.length ? "" : "none";
  for (const entry of entries) container.append(abstentionCard(entry));
  if (entries.length && state.review && state.review.calibrationNote) {
    container.append(calibrationNote());
  }
}

function calibrationNote() {
  const p = document.createElement("p");
  p.className = "calibration-note";
  p.textContent = state.review.calibrationNote;
  return p;
}

function thresholdLine(entry) {
  const wrap = document.createElement("div");
  wrap.className = "abstention-threshold";
  const confidence = entry.confidence || null;
  const threshold = entry.threshold || {};
  const score = document.createElement("div");
  score.className = "abstention-score";
  if (confidence && confidence.score != null && threshold.minConfidence != null) {
    score.textContent =
      "score " + confidence.score + " (" + (confidence.method || "unknown") + ")" +
      " < floor " + threshold.minConfidence;
  } else if (entry.details) {
    score.textContent = entry.details;
  } else {
    score.textContent = "no usable confidence";
  }
  wrap.append(score);
  if (threshold.pack && threshold.packVersion) {
    const provenance = document.createElement("div");
    provenance.className = "abstention-floor-source";
    const origin = threshold.source === "attribute" ? "attribute floor" : "pack default";
    provenance.textContent =
      "floor set by " + threshold.pack + " " + threshold.packVersion + " (" + origin + ")";
    wrap.append(provenance);
  }
  return wrap;
}

function abstentionCard(entry) {
  const card = document.createElement("div");
  card.className = "abstention-card";

  const head = document.createElement("div");
  head.className = "rule-head";
  const reason = document.createElement("span");
  reason.className = "abstention-reason";
  reason.textContent = REASON_LABELS[entry.reason] || entry.reason || "Abstained";
  const attr = document.createElement("span");
  attr.className = "node-attr";
  attr.textContent = shortAttr(entry.attribute);
  head.append(reason, attr);
  if (entry.routedTo) {
    const routed = document.createElement("span");
    routed.className = "rule-priority";
    routed.textContent = "routed to " + entry.routedTo;
    head.append(routed);
  }
  card.append(head, thresholdLine(entry));

  const facts = document.createElement("div");
  facts.className = "premises";
  for (const factId of entry.facts || []) facts.append(factChip(factId));
  if (facts.childNodes.length) card.append(facts);

  const review = state.review || {};
  if (review.available && entry.itemId && entry.itemStatus === "open") {
    card.append(correctionControls(entry));
  } else if (!review.available && review.note) {
    const note = document.createElement("p");
    note.className = "review-note";
    note.textContent = review.note;
    card.append(note);
  }
  return card;
}

function correctionControls(entry) {
  const wrap = document.createElement("div");
  wrap.className = "review-controls";

  const toggle = document.createElement("button");
  toggle.className = "download-btn review-toggle";
  toggle.type = "button";
  toggle.textContent = "Review & correct";
  toggle.setAttribute("aria-pressed", "false");

  const form = correctionForm(entry, toggle);
  form.classList.add("hidden");

  toggle.addEventListener("click", () => {
    const nowHidden = form.classList.toggle("hidden");
    toggle.setAttribute("aria-pressed", String(!nowHidden));
    if (!nowHidden) {
      const first = form.querySelector("input");
      if (first) first.focus();
    }
  });

  wrap.append(toggle, form);
  return wrap;
}

function correctionField(labelText, input) {
  const field = document.createElement("label");
  field.className = "review-field";
  const caption = document.createElement("span");
  caption.className = "field-label";
  caption.textContent = labelText;
  field.append(caption, input);
  return field;
}

function correctionForm(entry, toggle) {
  const form = document.createElement("form");
  form.className = "review-form";
  form.setAttribute("aria-label", "Correct " + shortAttr(entry.attribute));

  const machineFact = state.factIndex[(entry.facts || [])[0]] || null;

  const valueInput = document.createElement("input");
  valueInput.type = "text";
  valueInput.required = true;
  if (machineFact && machineFact.value != null) {
    valueInput.value = fmtValue(machineFact.value); // prefill from the machine fact
  }

  const nameInput = document.createElement("input");
  nameInput.type = "text";
  nameInput.required = true;
  nameInput.placeholder = "e.g. J. Reviewer";

  const roleInput = document.createElement("input");
  roleInput.type = "text";
  roleInput.required = true;
  roleInput.placeholder = "e.g. compliance-review";

  const error = document.createElement("p");
  error.className = "review-error hidden";
  error.setAttribute("role", "alert");

  const session = document.createElement("p");
  session.className = "review-session-note";
  session.textContent = (state.review && state.review.sessionNote) || "";

  const actions = document.createElement("div");
  actions.className = "review-actions";
  const submit = document.createElement("button");
  submit.className = "review-submit";
  submit.type = "submit";
  submit.textContent = "Apply correction";
  const cancel = document.createElement("button");
  cancel.className = "download-btn";
  cancel.type = "button";
  cancel.textContent = "Cancel";
  cancel.addEventListener("click", () => {
    form.classList.add("hidden");
    toggle.setAttribute("aria-pressed", "false");
  });
  actions.append(submit, cancel);

  form.append(
    correctionField("Corrected value", valueInput),
    correctionField("Reviewer name", nameInput),
    correctionField("Reviewer role", roleInput),
    error,
    session,
    actions
  );

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    submitCorrection(entry, {
      value: valueInput.value,
      reviewerName: nameInput.value,
      reviewerRole: roleInput.value,
    }, error, submit);
  });
  return form;
}

async function submitCorrection(entry, fields, errorEl, submitBtn) {
  const seq = ++state.requestSeq;
  errorEl.classList.add("hidden");
  submitBtn.disabled = true;
  setWorkspaceStatus("Applying correction", "loading");
  let payload = null;
  let errorText = null;
  try {
    const res = await fetch("/api/review/correct", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        scenarioId: state.scenario.id,
        itemId: entry.itemId,
        attribute: state.activeAttribute,
        asOfEffective: $("asof-input").value || state.scenario.defaultAsOf,
        value: fields.value,
        reviewerName: fields.reviewerName,
        reviewerRole: fields.reviewerRole,
      }),
    });
    if (res.ok) {
      payload = await res.json();
    } else {
      let detail = `HTTP ${res.status}`;
      try {
        const err = await res.json();
        if (err && err.detail) detail = String(err.detail);
      } catch { /* keep status text */ }
      errorText = detail;
    }
  } catch (e) {
    errorText = String(e);
  }
  if (seq !== state.requestSeq) return;
  submitBtn.disabled = false;

  if (errorText !== null) {
    errorEl.textContent = errorText;
    errorEl.classList.remove("hidden");
    setWorkspaceStatus("Correction failed", "error");
    return;
  }
  applyAdjudication(payload);
  setWorkspaceStatus("Correction applied — decision re-adjudicated", "info");
}

/* ---------- corrections applied this session ---------- */

function renderCorrections() {
  const container = $("corrections");
  container.replaceChildren();
  const review = state.review || {};
  const resolved = review.resolved || [];
  $("corrections-title").style.display = resolved.length ? "" : "none";
  for (const item of resolved) container.append(correctionCard(item));
  if (resolved.length) {
    if (review.calibrationNote) container.append(calibrationNote());
    const session = document.createElement("p");
    session.className = "review-session-note";
    session.textContent = review.sessionNote || "";
    container.append(session);
  }
}

function correctionCard(item) {
  const card = document.createElement("div");
  card.className = "correction-card";

  const head = document.createElement("div");
  head.className = "rule-head";
  const badge = document.createElement("span");
  badge.className = "correction-badge";
  badge.textContent = "Corrected";
  const attr = document.createElement("span");
  attr.className = "node-attr";
  attr.textContent = shortAttr(item.attribute);
  const value = document.createElement("span");
  value.className = "node-value";
  value.textContent = "= " + fmtValue(item.value);
  head.append(badge, attr, value);
  card.append(head);

  const who = document.createElement("div");
  who.className = "correction-actor";
  const actor = item.actor || {};
  who.textContent =
    "by " + (actor.id || "unknown reviewer") +
    (actor.role ? " (" + actor.role + ")" : "") +
    (item.resolvedAt ? " · " + fmtDay(item.resolvedAt) : "");
  card.append(who);

  if (item.supersededFactId) {
    const superseded = document.createElement("div");
    superseded.className = "correction-supersedes";
    superseded.textContent = "supersedes " + item.supersededFactId.slice(0, 34) + "…";
    superseded.title = item.supersededFactId;
    card.append(superseded);
  }

  const exportBtn = document.createElement("button");
  exportBtn.className = "download-btn";
  exportBtn.type = "button";
  exportBtn.textContent = "Export as golden case";
  exportBtn.addEventListener("click", () => downloadGoldenCase(item.itemId));

  const exportNote = document.createElement("p");
  exportNote.className = "review-note";
  exportNote.textContent =
    "Downloads a replayable golden-case bundle. Committing it into golden/ " +
    "is a human act — the demo never writes to the repository.";

  card.append(exportBtn, exportNote);
  return card;
}

function downloadGoldenCase(itemId) {
  const params = new URLSearchParams({ itemId });
  const a = document.createElement("a");
  a.href = "/api/review/golden-case?" + params.toString();
  document.body.append(a);
  a.click();
  a.remove();
}

function renderRulesFired() {
  const container = $("rules-fired");
  container.replaceChildren();
  const rules = (state.receipt && state.receipt.rulesFired) || [];
  for (const r of rules) {
    const card = document.createElement("div");
    card.className = "rule-card";

    const head = document.createElement("div");
    head.className = "rule-head";
    const id = document.createElement("span");
    id.className = "rule-id";
    id.textContent = r.ruleId;
    const version = document.createElement("span");
    version.className = "rule-version";
    version.textContent = "v" + r.version;
    head.append(id, version);
    if (typeof r.priority === "number") {
      const priority = document.createElement("span");
      priority.className = "rule-priority";
      priority.textContent = "priority " + r.priority;
      head.append(priority);
    }
    card.append(head);

    const citation = document.createElement("div");
    citation.className = "rule-citation";
    if (r.citation && r.citation.url) {
      const a = document.createElement("a");
      a.href = r.citation.url;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.textContent = r.citation.text;
      citation.append(a);
    } else if (r.citation) {
      citation.textContent = r.citation.text;
    }
    card.append(citation);

    const window_ = document.createElement("div");
    window_.className = "rule-window";
    window_.textContent =
      "effective " + fmtDay(r.effectiveFrom) +
      (r.effectiveTo ? " → " + fmtDay(r.effectiveTo) : " → open-ended");
    card.append(window_);

    if (Array.isArray(r.defeated) && r.defeated.length > 0) {
      const badge = document.createElement("span");
      badge.className = "defeated-badge";
      badge.textContent = "defeated: " + r.defeated.join(", ");
      card.append(badge);
    }
    container.append(card);
  }
  $("rules-title").style.display = rules.length ? "" : "none";
  $("rules-count").textContent = plural(rules.length, "rule");
}

/* ---------- exports ----------
 *
 * Every one of these is a server round trip, including the plain receipt,
 * which used to be assembled here with JSON.stringify. Hashed bytes must not
 * pass through a second JSON implementation: JavaScript has one number type,
 * so a receipt whose abstention carried a score of 1.0 was written back as 1
 * and no longer matched its own receiptSha256. Same rule the receipt viewer
 * follows in the other direction — move the text, never the object. */

function downloadReport(format) {
  if (!state.scenario || !state.activeAttribute) return;
  const params = new URLSearchParams({
    scenarioId: state.scenario.id,
    attribute: state.activeAttribute,
    asOfEffective: $("asof-input").value || state.scenario.defaultAsOf,
    format,
  });
  const a = document.createElement("a");
  a.href = "/api/report?" + params.toString();
  document.body.append(a);
  a.click();
  a.remove();
}

init().catch((e) => {
  const card = $("error-card");
  card.textContent = "Failed to load scenarios: " + String(e);
  card.classList.remove("hidden");
  setWorkspaceStatus("Demo unavailable", "error");
});
