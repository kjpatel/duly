/* duly evidence browser — vanilla JS, no dependencies.
 *
 * Same discipline as app.js and rules.js: every piece of server data reaches
 * the page through textContent, never innerHTML.
 *
 * This file renders three things the decision workspace deliberately does not:
 * the whole fact set of a case rather than one receipt's citations, the state
 * each fact is in at a chosen knowledge time, and the document's source bytes
 * next to the rendition the spans are measured against. It computes none of
 * them — liveness, conformance and citations are all decided server-side, and
 * the only thing this file knows about a fact is how to lay it out.
 */
"use strict";

const state = {
  cases: [],
  capabilities: {},
  caseId: null,
  data: null,
  knowledgeIndex: 0,
  activeDocId: null,
  activeFactId: null,
  detail: null,
  tab: "rendition",
  detailSeq: 0,
};

const $ = (id) => document.getElementById(id);

/* ---------- DOM helpers ---------- */

function el(tag, props, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key === "html") throw new Error("no innerHTML in this app");
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (key === "dataset") Object.assign(node.dataset, value);
    else if (key in node && key !== "list") node[key] = value;
    else node.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(typeof child === "string" ? document.createTextNode(child) : child);
  }
  return node;
}

/* DOM append() turns a null child into the text "null"; el() filters them.
 * Anything conditional appended to an existing node goes through here. */
function appendAll(node, ...children) {
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child);
  }
  return node;
}

function plural(count, singular, pluralForm = singular + "s") {
  return `${count} ${count === 1 ? singular : pluralForm}`;
}

function shortAttr(curie) {
  if (typeof curie !== "string") return "";
  const i = curie.indexOf(":");
  return i >= 0 ? curie.slice(i + 1) : curie;
}

function fmtValue(v) {
  if (v === null || v === undefined) return "—";
  if (typeof v !== "object") return String(v);
  if (v.kind === "money") return `${v.amount} ${v.currency}`;
  if (v.kind === "boolean") return v.value ? "true" : "false";
  if ("value" in v) return String(v.value);
  return JSON.stringify(v);
}

function fmtPoint(iso) {
  if (!iso) return "—";
  return iso.replace("T", " ").replace("Z", " UTC");
}

function shortHash(hash) {
  return typeof hash === "string" && hash.length > 16 ? hash.slice(0, 16) + "…" : hash || "—";
}

function setStatus(text, mode = "ready") {
  const status = $("workspace-status");
  $("workspace-status-text").textContent = text;
  for (const cls of ["loading", "error", "info", "fixture"]) {
    status.classList.toggle(cls, mode === cls);
  }
}

async function api(path) {
  const res = await fetch(path);
  let body = null;
  try {
    body = await res.json();
  } catch (err) {
    body = null;
  }
  if (!res.ok) {
    const detail = (body && body.detail) || `HTTP ${res.status}`;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return body;
}

function caseUrl(...segments) {
  return ["/api/evidence/cases", ...segments.map(encodeURIComponent)].join("/");
}

/* ---------- boot ---------- */

async function init() {
  setStatus("Loading cases", "loading");
  const data = await api("/api/evidence/cases");
  state.cases = data.cases;
  state.capabilities = data.capabilities;
  renderCaseOptions();
  $("case-select").addEventListener("change", (event) => selectCase(event.target.value));
  $("knowledge-range").addEventListener("input", onKnowledgeInput);

  const params = new URLSearchParams(window.location.search);
  const wanted = params.get("case");
  const start = state.cases.find((c) => c.id === wanted) || state.cases[0];
  if (!start) {
    setStatus("No cases found", "error");
    return;
  }
  if (params.get("tab") === "source") state.tab = "source";
  await selectCase(start.id, params.get("fact"), params.get("k"));
}

function renderCaseOptions() {
  const select = $("case-select");
  select.replaceChildren();
  const groups = new Map();
  for (const c of state.cases) {
    if (!groups.has(c.domainLabel)) groups.set(c.domainLabel, []);
    groups.get(c.domainLabel).push(c);
  }
  for (const [label, cases] of groups) {
    const group = el("optgroup", { label });
    for (const c of cases) group.append(el("option", { value: c.id, text: c.title }));
    select.append(group);
  }
}

/* Deep links: ?case=&fact=&k=&tab=. "Look at this fact, as of before the
 * correction" is only a useful sentence if it can carry a URL — the same
 * reason the rule studio deep-links a table. */
function syncLocation() {
  if (!state.caseId) return;
  const params = new URLSearchParams({ case: state.caseId });
  if (state.activeFactId) params.set("fact", state.activeFactId);
  if ((state.data.timeline || []).length) params.set("k", String(state.knowledgeIndex));
  if (state.tab !== "rendition") params.set("tab", state.tab);
  window.history.replaceState(null, "", `/evidence?${params.toString()}`);
}

/* ---------- case + knowledge time ---------- */

async function selectCase(caseId, wantedFactId = null, wantedIndex = null) {
  state.caseId = caseId;
  $("case-select").value = caseId;
  setStatus("Loading case", "loading");
  try {
    state.data = await api(caseUrl(caseId));
  } catch (err) {
    setStatus(err.message, "error");
    return;
  }
  let timeline = state.data.timeline || [];
  state.knowledgeIndex = Math.max(0, timeline.length - 1);
  const asked = Number(wantedIndex);
  if (wantedIndex !== null && Number.isInteger(asked) && asked >= 0 && asked < timeline.length) {
    state.knowledgeIndex = asked;
    try {
      state.data = await api(
        `${caseUrl(caseId)}?knowledge=${encodeURIComponent(timeline[asked].at)}`
      );
      timeline = state.data.timeline || [];
    } catch (err) {
      setStatus(err.message, "error");
      return;
    }
  }
  state.activeDocId = null;
  state.activeFactId = null;
  state.detail = null;
  afterCaseLoad(wantedFactId);
}

function afterCaseLoad(wantedFactId) {
  const data = state.data;
  renderKnowledge();
  renderIndex();
  const wanted = wantedFactId && data.facts.find((f) => f.id === wantedFactId);
  const firstDoc = (wanted && wanted.document && wanted.document.id) || firstDocumentId();
  activateDocument(firstDoc, { render: false });
  renderDocument();
  if (wanted) selectFact(wanted.id);
  else renderFact();
  setStatus(data.storeBacked ? "Store-backed" : "Disk-backed", data.storeBacked ? "ready" : "fixture");
  syncLocation();
}

function firstDocumentId() {
  const withFacts = state.data.facts.find((f) => f.document);
  if (withFacts) return withFacts.document.id;
  return state.data.documents.length ? state.data.documents[0].id : null;
}

/* Reloading at a new horizon keeps the reader where they were: same document,
 * same fact — the point of a timeline is to watch one thing change. */
async function reloadAtKnowledge() {
  const timeline = state.data.timeline || [];
  const point = timeline[state.knowledgeIndex];
  if (!point) return;
  const docId = state.activeDocId;
  const factId = state.activeFactId;
  setStatus("Projecting", "loading");
  try {
    state.data = await api(`${caseUrl(state.caseId)}?knowledge=${encodeURIComponent(point.at)}`);
  } catch (err) {
    setStatus(err.message, "error");
    return;
  }
  renderKnowledge();
  renderIndex();
  activateDocument(docId, { render: false });
  renderDocument();
  if (factId && state.data.facts.some((f) => f.id === factId)) selectFact(factId);
  else {
    state.activeFactId = null;
    state.detail = null;
    renderFact();
  }
  setStatus("Store-backed");
  syncLocation();
}

function onKnowledgeInput(event) {
  state.knowledgeIndex = Number(event.target.value);
  const point = (state.data.timeline || [])[state.knowledgeIndex];
  if (point) {
    $("knowledge-point").textContent = fmtPoint(point.at);
    $("knowledge-caption").textContent = point.label;
  }
  clearTimeout(onKnowledgeInput.timer);
  onKnowledgeInput.timer = setTimeout(reloadAtKnowledge, 90);
}

function renderKnowledge() {
  const bar = $("knowledge-bar");
  const timeline = state.data.timeline || [];
  const range = $("knowledge-range");
  const ticks = $("knowledge-ticks");
  ticks.replaceChildren();

  if (!timeline.length) {
    bar.classList.add("disabled");
    range.disabled = true;
    range.max = 0;
    $("knowledge-point").textContent = "No event log";
    $("knowledge-caption").textContent =
      state.data.note || "This case has no knowledge timeline.";
    $("knowledge-counts").replaceChildren();
    return;
  }

  bar.classList.remove("disabled");
  range.disabled = false;
  range.max = String(timeline.length - 1);
  range.value = String(state.knowledgeIndex);
  const point = timeline[state.knowledgeIndex];
  $("knowledge-point").textContent = fmtPoint(point.at);
  $("knowledge-caption").textContent = point.label;

  for (const [i, entry] of timeline.entries()) {
    ticks.append(
      el("span", {
        class: "knowledge-tick" + (i === state.knowledgeIndex ? " active" : ""),
        text: (entry.at || "").slice(0, 10),
      })
    );
  }

  const counts = $("knowledge-counts");
  counts.replaceChildren();
  const order = ["live", "superseded", "retracted", "future"];
  const labels = {
    live: "live",
    superseded: "superseded",
    retracted: "retracted",
    future: "not yet known",
  };
  for (const key of order) {
    const n = state.data.counts[key] || 0;
    if (!n) continue;
    counts.append(
      el("span", { class: `state-chip ${key}` }, el("span", { class: "state-dot" }), `${n} ${labels[key]}`)
    );
  }
}

/* ---------- index pane ---------- */

function factsForDocument(docId) {
  return state.data.facts.filter((f) => (f.document ? f.document.id : null) === docId);
}

function renderIndex() {
  const list = $("index-list");
  list.replaceChildren();
  $("index-count").textContent = plural(state.data.facts.length, "fact");
  $("index-subtitle").textContent = state.data.caseId;

  for (const doc of state.data.documents) {
    const facts = factsForDocument(doc.id);
    const head = el(
      "button",
      {
        class: "index-doc" + (doc.id === state.activeDocId ? " active" : ""),
        type: "button",
        dataset: { docId: doc.id },
        onclick: () => activateDocument(doc.id),
      },
      el("span", { class: "index-doc-title", text: doc.title }),
      el("span", {
        class: "index-doc-meta",
        text: `${plural(facts.length, "fact")} · ${doc.source.available ? "source + rendition" : "rendition only"}`,
      })
    );
    list.append(head);
    const group = el("div", { class: "index-facts" });
    for (const fact of facts) group.append(factRow(fact));
    if (!facts.length) group.append(el("p", { class: "empty", text: "No facts cite this document." }));
    list.append(group);
  }

  // Not every fact is grounded in a document — a reviewer's correction is
  // grounded in an attestation. Grouping by grounding kind names what they
  // are instead of defining them by what they are not.
  const byKind = new Map();
  for (const fact of state.data.facts) {
    if (fact.document) continue;
    const kind = fact.groundingKind || "ungrounded";
    if (!byKind.has(kind)) byKind.set(kind, []);
    byKind.get(kind).push(fact);
  }
  for (const [kind, facts] of byKind) {
    list.append(
      el(
        "div",
        { class: "index-doc static" },
        el("span", { class: "index-doc-title", text: `${kind} grounding` }),
        el("span", { class: "index-doc-meta", text: `${plural(facts.length, "fact")} · not in a document` })
      )
    );
    const group = el("div", { class: "index-facts" });
    for (const fact of facts) group.append(factRow(fact));
    list.append(group);
  }

  const note = $("store-note");
  if (state.data.note) {
    note.textContent = state.data.note;
    note.hidden = false;
  } else {
    note.hidden = true;
  }
}

function factRow(fact) {
  return el(
    "button",
    {
      class: "fact-row" + (fact.id === state.activeFactId ? " active" : "") + ` ${fact.state}`,
      type: "button",
      dataset: { factId: fact.id },
      onclick: () => selectFact(fact.id),
    },
    el("span", { class: "fact-row-attr", text: shortAttr(fact.attribute) }),
    el("span", { class: "fact-row-value", text: fmtValue(fact.value) }),
    el("span", { class: `state-chip ${fact.state}` }, el("span", { class: "state-dot" }), fact.state === "future" ? "not yet" : fact.state)
  );
}

/* ---------- document pane ---------- */

function activeDocument() {
  return state.data.documents.find((d) => d.id === state.activeDocId) || null;
}

function activateDocument(docId, { render = true } = {}) {
  const exists = state.data.documents.some((d) => d.id === docId);
  state.activeDocId = exists ? docId : (state.data.documents[0] || {}).id || null;
  const doc = activeDocument();
  if (doc && state.tab === "source" && !doc.source.available) state.tab = "rendition";
  for (const btn of $("index-list").querySelectorAll(".index-doc")) {
    btn.classList.toggle("active", btn.dataset.docId === state.activeDocId);
  }
  if (render) renderDocument();
}

function renderDocument() {
  const doc = activeDocument();
  const tabs = $("doc-tabs");
  const view = $("doc-view");
  tabs.replaceChildren();
  view.replaceChildren();

  if (!doc) {
    $("doc-title").textContent = "No documents";
    $("doc-badge").textContent = "—";
    return;
  }
  $("doc-title").textContent = doc.title;
  $("doc-subtitle").textContent = doc.id;

  const spans = factsForDocument(doc.id).filter((f) => f.charSpan);
  $("doc-badge").textContent = plural(spans.length, "span");

  tabs.append(
    tabButton("rendition", "Rendition", true, null),
    tabButton(
      "source",
      "Source PDF",
      doc.source.available,
      doc.source.available ? null : "No committed source bytes for this document."
    )
  );

  if (state.tab === "source") renderSource(doc, view);
  else renderRendition(doc, view);
}

function tabButton(id, label, enabled, disabledReason) {
  return el("button", {
    class: "tab" + (state.tab === id ? " active" : ""),
    type: "button",
    role: "tab",
    disabled: !enabled,
    title: disabledReason || label,
    "aria-selected": String(state.tab === id),
    text: label,
    onclick: () => {
      state.tab = id;
      renderDocument();
      syncLocation();
    },
  });
}

/* Build the highlighted rendition by slicing the text at span boundaries.
 * Never regex-replaces, never sets innerHTML from raw text. A superseded or
 * not-yet-known fact keeps its mark, styled to say so — a browser that hid
 * them would be the receipt view again, and supersession is the thing worth
 * seeing here. */
function renderRendition(doc, view) {
  const text = doc.renditionText || "";
  const spans = [];
  for (const fact of factsForDocument(doc.id)) {
    const span = fact.charSpan;
    if (!span) continue;
    const { start, end } = span;
    if (!Number.isInteger(start) || !Number.isInteger(end)) continue;
    if (start < 0 || end > text.length || end <= start) continue;
    spans.push({ start, end, fact });
  }
  spans.sort((a, b) => a.start - b.start || a.end - b.end);

  const body = el("div", { class: "doc-text" });
  const skipped = [];
  let cursor = 0;
  for (const span of spans) {
    if (span.start < cursor) {
      // Two facts quoting overlapping text cannot both be drawn without
      // nesting marks. Rather than silently losing one, the reader is told
      // which — an undrawn span still has a row in the index.
      skipped.push(span.fact);
      continue;
    }
    if (span.start > cursor) body.append(document.createTextNode(text.slice(cursor, span.start)));
    body.append(
      el("mark", {
        id: markId(span.fact.id),
        class: `${span.fact.state}` + (span.fact.id === state.activeFactId ? " selected" : ""),
        title: `${shortAttr(span.fact.attribute)} — ${span.fact.state}`,
        tabIndex: 0,
        role: "button",
        text: text.slice(span.start, span.end),
        onclick: () => selectFact(span.fact.id),
        onkeydown: (event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            selectFact(span.fact.id);
          }
        },
      })
    );
    cursor = span.end;
  }
  if (cursor < text.length) body.append(document.createTextNode(text.slice(cursor)));

  // DOM append() stringifies null; el() filters it. Everything conditional
  // goes through appendAll.
  appendAll(
    view,
    el(
      "p",
      { class: "legend" },
      "Character spans are offsets into this rendition — one extractor's reading of the source bytes. ",
      "The source PDF carries no span coordinates, so it is shown without highlights rather than with guessed ones."
    ),
    skipped.length
      ? el("p", { class: "legend" }, [
          `${plural(skipped.length, "span")} ${skipped.length === 1 ? "overlaps" : "overlap"} an earlier one and cannot be drawn: `,
          ...skipped.map((fact, i) =>
            el(
              "button",
              {
                class: "link-btn",
                type: "button",
                text: (i ? ", " : "") + shortAttr(fact.attribute),
                onclick: () => selectFact(fact.id),
              }
            )
          ),
        ])
      : null,
    body
  );
}

function renderSource(doc, view) {
  const source = doc.source;
  const sourceUrl = caseUrl(state.caseId, "documents", doc.id, "source");
  const verified =
    source.verified === true
      ? "matches the sha256 the facts cite"
      : source.verified === false
        ? "does NOT match the sha256 the facts cite"
        : "no declared sha256 to compare against";
  view.append(
    el(
      "p",
      { class: "legend" + (source.verified === false ? " bad" : "") },
      `These are the bytes hashed into every fact's grounding — ${verified}.`
    ),
    el("dl", { class: "kv" },
      kv("sha256", source.sha256 || "—", true),
      kv("Size", source.bytes === null ? "—" : `${source.bytes} bytes`)
    ),
    el("iframe", {
      class: "doc-source",
      title: `${doc.title} (source PDF)`,
      src: sourceUrl,
    }),
    // Not every browser embeds PDFs; the bytes must stay reachable either way.
    el("p", { class: "muted" },
      el("a", { class: "link-btn", href: sourceUrl, target: "_blank", rel: "noopener", text: "Open the source PDF in a new tab" })
    )
  );
}

function markId(factId) {
  return `mark-${factId.replace(/[^A-Za-z0-9_-]/g, "-")}`;
}

function focusMark(factId) {
  const mark = document.getElementById(markId(factId));
  if (!mark) return;
  mark.scrollIntoView({ behavior: "smooth", block: "center" });
  mark.classList.remove("flash");
  void mark.offsetWidth; // restart the transition
  mark.classList.add("flash");
  setTimeout(() => mark.classList.remove("flash"), 1400);
}

/* ---------- fact inspector ---------- */

async function selectFact(factId) {
  const record = state.data.facts.find((f) => f.id === factId);
  if (!record) return;
  state.activeFactId = factId;
  state.detail = null;
  for (const btn of $("index-list").querySelectorAll(".fact-row")) {
    btn.classList.toggle("active", btn.dataset.factId === factId);
  }
  if (record.document && record.document.id !== state.activeDocId) {
    activateDocument(record.document.id);
  } else {
    renderDocument();
  }
  renderFact();
  syncLocation();
  if (record.document && state.tab === "rendition") requestAnimationFrame(() => focusMark(factId));

  const seq = ++state.detailSeq;
  const params = new URLSearchParams();
  if (state.data.knowledge) params.set("knowledge", state.data.knowledge);
  try {
    const detail = await api(
      `${caseUrl(state.caseId, "facts", factId)}?${params.toString()}`
    );
    if (seq !== state.detailSeq) return;
    state.detail = detail;
  } catch (err) {
    if (seq !== state.detailSeq) return;
    state.detail = { error: err.message };
  }
  renderFact();
}

function kv(label, value, mono = false) {
  return el(
    "div",
    { class: "kv-row" },
    el("dt", { text: label }),
    el("dd", { class: mono ? "mono wrap" : null, text: value })
  );
}

function section(title, ...children) {
  return el("section", { class: "fact-section" }, el("h3", { text: title }), ...children);
}

const STATE_COPY = {
  live: "Live at this knowledge time.",
  superseded: "Superseded — a later fact replaced it.",
  retracted: "Retracted — withdrawn without replacement.",
  future: "Not yet known at this knowledge time.",
};

function renderFact() {
  const body = $("fact-body");
  body.replaceChildren();
  const badge = $("fact-state");
  const record = state.data.facts.find((f) => f.id === state.activeFactId);

  if (!record) {
    badge.hidden = true;
    $("fact-title").textContent = "Fact inspector";
    $("fact-subtitle").textContent = "Select a fact to see its record";
    body.append(
      el("p", { class: "empty", text: "Pick a fact from the index, or click a highlighted span." })
    );
    return;
  }

  $("fact-title").textContent = shortAttr(record.attribute);
  $("fact-subtitle").textContent = record.entity ? record.entity.id : "";
  badge.hidden = false;
  badge.textContent = record.state === "future" ? "not yet known" : record.state;
  badge.className = `pane-badge state-${record.state}`;

  body.append(
    el(
      "div",
      { class: `fact-headline ${record.state}` },
      el("div", { class: "fact-value", text: fmtValue(record.value) }),
      el("p", { class: "fact-state-copy", text: STATE_COPY[record.state] || "" }),
      record.supersededBy &&
        el(
          "button",
          {
            class: "link-btn",
            type: "button",
            text: "Show the fact that replaced it",
            onclick: () => selectFact(record.supersededBy),
          }
        ),
      record.supersedes &&
        el(
          "button",
          {
            class: "link-btn",
            type: "button",
            text: "Show the fact it replaced",
            onclick: () => selectFact(record.supersedes),
          }
        ),
      record.pendingSupersededBy &&
        el("p", {
          class: "fact-pending",
          text: "A later fact supersedes this one — drag the knowledge dial forward to see it.",
        })
    )
  );

  const groundingRows = [kv("Kind", record.groundingKind || "—")];
  if (record.document) {
    groundingRows.push(
      kv("Document", record.document.title),
      kv("Page", record.page === null || record.page === undefined ? "—" : String(record.page)),
      kv("Char span", record.charSpan ? `${record.charSpan.start}–${record.charSpan.end}` : "—"),
      kv("Document sha256", shortHash(record.documentSha256), true),
      kv(
        "Rendition",
        record.rendition
          ? `${record.rendition.extractor} ${record.rendition.extractorVersion}`
          : "—"
      )
    );
  }
  for (const [key, value] of Object.entries(record.groundingDetail || {})) {
    groundingRows.push(kv(key, typeof value === "object" ? JSON.stringify(value) : String(value)));
  }
  body.append(
    section(
      "Grounding",
      el("dl", { class: "kv" }, ...groundingRows),
      record.quote && el("blockquote", { class: "fact-quote", text: record.quote })
    )
  );

  const provenance = record.provenance || {};
  body.append(
    section(
      "Provenance",
      el(
        "dl",
        { class: "kv" },
        kv("Asserted by", provenance.label || record.assertionKind || "—"),
        kv("Kind", record.assertionKind || "—"),
        kv("Recorded at", fmtPoint(record.recordedAt)),
        kv("Effective from", record.effectiveFrom || "—"),
        kv("Effective to", record.effectiveTo || "open")
      )
    )
  );

  if (record.confidence && record.confidence.score !== null && record.confidence.score !== undefined) {
    body.append(
      section(
        "Confidence",
        el(
          "dl",
          { class: "kv" },
          kv("Score", String(record.confidence.score)),
          kv("Method", record.confidence.method || "—"),
          kv("Calibration", record.confidence.calibrationRef || "—")
        )
      )
    );
  }

  body.append(
    section(
      "Identity",
      el(
        "dl",
        { class: "kv" },
        kv("Content hash", record.contentHash || "—", true),
        kv("Fact id", record.id || "—", true)
      )
    )
  );

  if (state.detail && state.detail.error) {
    body.append(el("p", { class: "error-note", text: state.detail.error }));
    return;
  }
  if (!state.detail) {
    body.append(el("p", { class: "empty", text: "Loading ontology, history and citations…" }));
    return;
  }
  body.append(conformanceSection(state.detail.conformance));
  if (state.detail.history.length) body.append(historySection(state.detail.history));
  body.append(citationSection(state.detail.citations));
}

function conformanceSection(conformance) {
  if (!conformance || !conformance.available) {
    return section(
      "Ontology",
      el("p", { class: "empty", text: (conformance && conformance.note) || "Unavailable." })
    );
  }
  const rows = [kv("Pinned schema", conformance.ref, true)];
  const slot = conformance.slot;
  if (slot) {
    rows.push(kv("Declared on", slot.declaredOn, true));
    rows.push(kv("Value kind", slot.kind));
    rows.push(kv("Required", slot.required ? "yes" : "no"));
    if (slot.enum) {
      rows.push(kv("Code system", slot.enum.codeSystem || "—"));
      rows.push(
        kv(
          "Permitted",
          slot.enum.openCodeSet
            ? `${slot.enum.values.length} listed (open set)`
            : slot.enum.values.join(", ")
        )
      );
    }
  }
  const verdict = el(
    "p",
    { class: `verdict-line ${conformance.conformant ? "ok" : "bad"}` },
    conformance.conformant
      ? "Conforms to the ontology its schemaRef pins."
      : "Does not conform to the ontology its schemaRef pins."
  );
  const issues = conformance.issues.map((issue) =>
    el("li", {}, el("code", { text: issue.code }), " ", issue.message)
  );
  return section(
    "Ontology",
    verdict,
    el("dl", { class: "kv" }, ...rows),
    issues.length ? el("ul", { class: "issue-list" }, ...issues) : null
  );
}

const HISTORY_COPY = {
  asserted: "asserted",
  superseded: "superseded by a later fact",
  retracted: "retracted",
};

function historySection(history) {
  const items = history.map((event) =>
    el(
      "li",
      {
        class:
          "history-event" + (event.self ? " self" : "") + (event.future ? " future" : ""),
        title: event.future ? "After the knowledge time selected above" : null,
      },
      el("span", { class: "history-when", text: fmtPoint(event.recordedAt) }),
      el("span", { class: "history-what", text: HISTORY_COPY[event.kind] || event.kind }),
      event.future && el("span", { class: "history-future", text: "not yet known" }),
      !event.self &&
        el("button", {
          class: "link-btn",
          type: "button",
          text: shortAttr(event.attribute || event.factId),
          onclick: () => selectFact(event.factId),
        })
    )
  );
  return section(
    "History",
    el("p", { class: "muted", text: "Every event on this fact and its supersession chain." }),
    el("ul", { class: "history-list" }, ...items)
  );
}

function citationSection(citations) {
  if (!citations || !citations.available) {
    return section(
      "Cited by",
      el("p", { class: "empty", text: (citations && citations.note) || "Unavailable." })
    );
  }
  const items = (citations.questions || []).map((entry) => {
    const role =
      entry.role === "input"
        ? "cited in the derivation"
        : entry.role === "abstained"
          ? "abstained on — the answer was reached without it"
          : entry.note || "not in the derivation";
    return el(
      "li",
      { class: "citation" + (entry.role ? " used" : "") },
      el("a", {
        class: "link-btn",
        // Both halves matter: the workspace opens on the first question of the
        // first scenario unless told otherwise, and this link is about one
        // question of one case.
        href:
          `/?scenario=${encodeURIComponent(state.caseId)}` +
          `&question=${encodeURIComponent(entry.attribute)}`,
        text: entry.question,
      }),
      el("span", { class: "citation-role", text: role })
    );
  });
  return section(
    "Cited by",
    el("p", {
      class: "muted",
      text:
        `Adjudicated at effective ${(citations.effective || "").slice(0, 10)}, from the facts live at this ` +
        "knowledge time. Cited means the fact appears in the derivation of the answer — a live fact read by " +
        "a rule that did not survive is not cited, and that is a real distinction, not a gap.",
    }),
    el("ul", { class: "citation-list" }, ...items)
  );
}

init().catch((err) => setStatus(err.message, "error"));
