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
  lastVerdictKey: null,
  requestSeq: 0,
};

const $ = (id) => document.getElementById(id);

/* ---------- formatting helpers ---------- */

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
  const res = await fetch("/api/scenarios");
  state.scenarios = await res.json();

  const select = $("scenario-select");
  select.replaceChildren();
  for (const sc of state.scenarios) {
    const opt = document.createElement("option");
    opt.value = sc.id;
    opt.textContent = sc.title;
    select.append(opt);
  }
  select.addEventListener("change", () => selectScenario(select.value));
  $("asof-input").addEventListener("change", () => {
    if (state.scenario && state.activeAttribute) runAdjudication();
  });
  $("download-receipt").addEventListener("click", downloadReceipt);
  $("download-report-md").addEventListener("click", () => downloadReport("md"));
  $("download-report-pdf").addEventListener("click", () => downloadReport("pdf"));

  if (state.scenarios.length > 0) {
    select.value = state.scenarios[0].id;
    await selectScenario(state.scenarios[0].id);
  }
}

async function selectScenario(id) {
  const scenario = state.scenarios.find((s) => s.id === id);
  if (!scenario) return;
  state.scenario = scenario;
  state.documents = new Map();
  state.activeDocId = null;
  state.receipt = null;
  state.factIndex = {};
  state.lastVerdictKey = null;
  $("answer-card").classList.add("hidden");
  $("error-card").classList.add("hidden");
  $("derivation").replaceChildren();
  $("rules-fired").replaceChildren();
  setDownloadsEnabled(false);

  $("asof-input").value = scenario.defaultAsOf || "";

  await Promise.all(scenario.documents.map(async (d) => {
    const res = await fetch(
      `/api/document/${encodeURIComponent(scenario.id)}/${encodeURIComponent(d.id)}`
    );
    state.documents.set(d.id, res.ok ? await res.json()
                                     : { title: d.title, renditionText: "" });
  }));

  renderTabs();
  if (scenario.documents.length > 0) activateDoc(scenario.documents[0].id);
  renderQuestions();

  if (scenario.questions.length > 0) {
    state.activeAttribute = scenario.questions[0].attribute;
    highlightActiveQuestion();
    await runAdjudication();
  }
}

/* ---------- document pane ---------- */

function renderTabs() {
  const tabs = $("doc-tabs");
  tabs.replaceChildren();
  for (const d of state.scenario.documents) {
    const btn = document.createElement("button");
    btn.className = "tab";
    btn.textContent = d.title;
    btn.dataset.docId = d.id;
    btn.addEventListener("click", () => activateDoc(d.id));
    tabs.append(btn);
  }
}

function activateDoc(docId) {
  state.activeDocId = docId;
  for (const btn of $("doc-tabs").querySelectorAll(".tab")) {
    btn.classList.toggle("active", btn.dataset.docId === docId);
  }
  renderDocument();
}

/* Build the highlighted rendition by slicing the text at span boundaries.
 * Never regex-replaces, never sets innerHTML from raw text. */
function renderDocument() {
  const container = $("doc-text");
  container.replaceChildren();
  const doc = state.documents.get(state.activeDocId);
  if (!doc) return;
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
    btn.textContent = q.question;
    btn.dataset.attribute = q.attribute;
    btn.addEventListener("click", () => {
      state.activeAttribute = q.attribute;
      highlightActiveQuestion();
      runAdjudication();
    });
    chips.append(btn);
  }
}

function highlightActiveQuestion() {
  for (const btn of $("question-chips").querySelectorAll(".chip")) {
    btn.classList.toggle("active", btn.dataset.attribute === state.activeAttribute);
  }
}

function verdictFor(decision) {
  const value = decision && decision.value;
  if (value && value.kind === "boolean" &&
      shortAttr(decision.attribute).toLowerCase().includes("compliant")) {
    return value.value
      ? { text: "Compliant", cls: "pos" }
      : { text: "Not compliant", cls: "neg" };
  }
  if (value && value.kind === "boolean") {
    return value.value ? { text: "Yes", cls: "pos" } : { text: "No", cls: "neg" };
  }
  return { text: fmtValue(value), cls: "" };
}

async function runAdjudication() {
  const seq = ++state.requestSeq;
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
    $("answer-card").classList.add("hidden");
    const card = $("error-card");
    card.textContent = errorText;
    card.classList.remove("hidden");
    return;
  }
  $("error-card").classList.add("hidden");

  state.receipt = payload.receipt;
  state.factIndex = payload.factIndex || {};
  state.engineMode = payload.engineMode;

  renderAnswer(payload);
  renderDerivation();
  renderRulesFired();
  renderDocument(); // re-highlight with the (possibly new) fact index
  setDownloadsEnabled(true);
}

function setDownloadsEnabled(enabled) {
  for (const id of ["download-receipt", "download-report-md", "download-report-pdf"]) {
    $(id).disabled = !enabled;
  }
}

function renderAnswer(payload) {
  const card = $("answer-card");
  card.classList.remove("hidden");

  const badge = $("engine-badge");
  badge.textContent = payload.engineMode;
  badge.className = "badge " + (payload.engineMode === "live" ? "live" : "fixture");
  $("fixture-note").classList.toggle("hidden", payload.engineMode !== "fixture");

  const asOf = state.receipt && state.receipt.asOf;
  $("answer-asof").textContent = asOf
    ? `effective ${fmtDay(asOf.effective)} · knowledge ${fmtDay(asOf.knowledge)}`
    : "";

  const v = verdictFor(state.receipt ? state.receipt.decision : null);
  const verdictEl = $("verdict");
  verdictEl.textContent = v.text;
  verdictEl.className = "verdict" + (v.cls ? " " + v.cls : "");
  $("answer-text").textContent = payload.answer || "";

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
}

/* ---------- receipt download ---------- */

function downloadReceipt() {
  if (!state.receipt) return;
  const blob = new Blob([JSON.stringify(state.receipt, null, 2)],
                        { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  const sha = state.receipt.receiptSha256;
  a.download = sha ? `receipt-${sha.slice(0, 12)}.json` : "receipt.json";
  document.body.append(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

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
});
