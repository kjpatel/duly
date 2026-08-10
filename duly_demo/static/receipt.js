/* duly receipt viewer — vanilla JS, no dependencies.
 *
 * Same discipline as app.js and rules.js: every piece of server data reaches
 * the page through textContent, never innerHTML. The only markup this file
 * writes is markup it constructs itself.
 *
 * This file renders two things and derives neither. The report is a list of
 * typed blocks the kernel's own report renderer produced
 * (duly_kernel.report.render_report_blocks — the same section structure
 * behind the Markdown and the PDF), and the verification result is the
 * server's, computed by re-hashing and re-adjudicating. Nothing here decides
 * whether a receipt holds; it decides how to say so.
 */
"use strict";

const state = {
  corpus: [],
  packs: [],
  filter: "",
  pack: "",
  caseId: null,
  view: null,
  tab: "report",
  loading: false,
  files: [],
  matches: [],
  open: false,
  active: -1,
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

function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

function plural(count, singular, pluralForm = singular + "s") {
  return `${count} ${count === 1 ? singular : pluralForm}`;
}

function shortHash(value) {
  if (typeof value !== "string") return "";
  const hex = value.split(":").pop();
  return hex.slice(0, 12) + "…";
}

function setStatus(text, mode = "ready") {
  const status = $("workspace-status");
  $("workspace-status-text").textContent = text;
  for (const cls of ["loading", "error", "info", "fixture"]) {
    status.classList.toggle(cls, mode === cls);
  }
}

async function getJSON(url, options) {
  const res = await fetch(url, options);
  let body = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  if (!res.ok) {
    const detail = body && body.detail ? body.detail : `${res.status} ${res.statusText}`;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return body;
}

/* ---------- the receipt picker ----------
 *
 * 351 receipts is too many to browse and exactly the right number to search,
 * so the corpus is a combobox in the toolbar rather than a rail down the
 * side: the reader arrives knowing which receipt they want (a case id from a
 * report, a hash from a log line), and the horizontal space is worth more to
 * the report and the verification rail.
 *
 * The whole index is already client-side, so filtering is local and the
 * dropdown is only ever a view of `state.matches`. */

const MATCH_CAP = 40;

function matchesFilter(row) {
  if (state.pack && row.pack !== state.pack) return false;
  const q = state.filter.trim().toLowerCase();
  if (!q) return true;
  return (
    row.caseId.toLowerCase().includes(q) ||
    row.receiptSha256.startsWith(q.replace(/^.*:/, ""))
  );
}

function recomputeMatches() {
  state.matches = state.corpus.filter(matchesFilter);
  if (state.active >= state.matches.length) state.active = state.matches.length - 1;
  if (state.active < 0 && state.matches.length) state.active = 0;
}

function optionId(index) {
  return `corpus-option-${index}`;
}

function renderPicker() {
  const input = $("corpus-search");
  const pop = $("corpus-pop");
  const list = $("corpus-listbox");
  const note = $("corpus-note");
  if (!input) return;

  input.placeholder = `Search ${state.corpus.length} receipts by case id or hash`;
  input.setAttribute("aria-expanded", state.open ? "true" : "false");
  pop.hidden = !state.open;
  if (!state.open) {
    input.removeAttribute("aria-activedescendant");
    return;
  }

  clear(list);
  const shown = state.matches.slice(0, MATCH_CAP);
  note.textContent = !state.matches.length
    ? "No receipt in the corpus matches that — a receipt from outside this repository will not be here."
    : state.matches.length > shown.length
      ? `${plural(state.matches.length, "match", "matches")}, showing ${shown.length}. Keep typing to narrow.`
      : plural(state.matches.length, "match", "matches");

  shown.forEach((row, index) => {
    list.append(
      el(
        "li",
        {
          id: optionId(index),
          role: "option",
          class:
            "combo-option" +
            (index === state.active ? " active" : "") +
            (row.caseId === state.caseId ? " current" : ""),
          "aria-selected": index === state.active ? "true" : "false",
          // Commit on mousedown: a click would land after the input's blur
          // has already closed the list out from under the pointer.
          onmousedown: (event) => {
            event.preventDefault();
            commitPick(row.caseId);
          },
          onmousemove: () => {
            if (state.active === index) return;
            state.active = index;
            renderPicker();
          },
        },
        el(
          "span",
          { class: "combo-main" },
          el("span", { class: "combo-case", text: row.caseId }),
          el("span", { class: "combo-value", text: row.value })
        ),
        el(
          "span",
          { class: "combo-meta" },
          el("span", { text: row.pack }),
          el("span", { "aria-hidden": "true", text: "·" }),
          el("span", { text: row.attributeShort }),
          el("span", { "aria-hidden": "true", text: "·" }),
          el("span", { text: row.effective }),
          row.abstentions
            ? el("span", { class: "combo-tag", text: plural(row.abstentions, "abstention") })
            : null,
          el("span", { class: "combo-hash mono", text: shortHash(row.receiptSha256) })
        )
      )
    );
  });

  const active = state.active >= 0 && state.active < shown.length;
  if (active) {
    input.setAttribute("aria-activedescendant", optionId(state.active));
    const node = list.children[state.active];
    if (node && node.scrollIntoView) node.scrollIntoView({ block: "nearest" });
  } else {
    input.removeAttribute("aria-activedescendant");
  }
}

function openPicker() {
  recomputeMatches();
  state.open = true;
  renderPicker();
}

function closePicker() {
  state.open = false;
  renderPicker();
}

function movePick(delta) {
  if (!state.open) {
    openPicker();
    return;
  }
  const limit = Math.min(state.matches.length, MATCH_CAP);
  if (!limit) return;
  state.active = (state.active + delta + limit) % limit;
  renderPicker();
}

function commitPick(caseId) {
  state.filter = "";
  $("corpus-search").value = "";
  closePicker();
  openCase(caseId);
}

/* ---------- report blocks ---------- */
//
// One renderer per block tag the kernel emits. A tag this file does not know
// is skipped rather than guessed at — a new block type should show up as
// missing, not as mangled prose.

function renderBlock(block) {
  if (block.tag === "para") return el("p", { class: "report-para", text: block.text });
  if (block.tag === "subhead") return el("h4", { class: "report-subhead", text: block.text });
  if (block.tag === "code") return el("pre", { class: "report-code", text: block.text });
  if (block.tag === "kv") {
    const dl = el("dl", { class: "report-kv" });
    for (const row of block.rows || []) {
      dl.append(
        el("dt", { text: row.label }),
        el("dd", { class: row.mono ? "mono" : null, text: row.value })
      );
    }
    return dl;
  }
  if (block.tag === "steps") {
    const ol = el("ol", { class: "report-steps" });
    for (const step of block.steps || []) {
      const li = el("li", {}, el("p", { class: "step-lead", text: step.lead }));
      if ((step.evidence || []).length) {
        const ul = el("ul", { class: "step-evidence" });
        for (const line of step.evidence) ul.append(el("li", { text: line }));
        li.append(ul);
      }
      ol.append(li);
    }
    return ol;
  }
  return null;
}

function renderReport(sections) {
  const wrap = el("div", { class: "report" });
  for (const section of sections || []) {
    const node = el("section", { class: "report-section" });
    if (section.title) node.append(el("h3", { text: section.title }));
    for (const block of section.blocks || []) {
      const rendered = renderBlock(block);
      if (rendered) node.append(rendered);
    }
    wrap.append(node);
  }
  return wrap;
}

/* ---------- report pane ---------- */

function renderTabs() {
  const tabs = $("report-tabs");
  clear(tabs);
  if (!state.view) return;
  for (const [id, label] of [["report", "Report"], ["json", "Receipt JSON"]]) {
    tabs.append(
      el("button", {
        type: "button",
        role: "tab",
        class: "tab" + (state.tab === id ? " active" : ""),
        "aria-selected": state.tab === id ? "true" : "false",
        text: label,
        onclick: () => {
          state.tab = id;
          renderTabs();
          renderReportBody();
        },
      })
    );
  }
}

function renderReportBody() {
  const body = $("report-body");
  clear(body);
  if (!state.view) {
    body.append(
      el("p", {
        class: "empty",
        text:
          "Search the committed corpus above, or paste a receipt you already " +
          "have. Either way it is verified before it is shown.",
      })
    );
    return;
  }
  if (state.tab === "json") {
    body.append(
      el("pre", {
        class: "report-code json",
        text: JSON.stringify(state.view.receipt, null, 2),
      })
    );
    return;
  }
  body.append(renderReport(state.view.report));
}

function renderReportHead() {
  const view = state.view;
  const subtitle = $("report-subtitle");
  const badge = $("resolution-badge");
  if (!view) {
    subtitle.textContent = "Select a receipt";
    badge.hidden = true;
    return;
  }
  const decision = view.receipt.decision || {};
  subtitle.textContent = view.caseId
    ? `${view.caseId} — ${decision.attribute || ""}`
    : decision.attribute || "receipt";

  const resolved = view.resolution.state === "resolved";
  badge.hidden = false;
  badge.textContent = resolved ? "resolved" : "partial";
  badge.classList.toggle("partial", !resolved);
}

/* ---------- verification pane ---------- */

const CHECK_STATE_LABEL = { pass: "pass", fail: "fail", unavailable: "not checked" };

function renderVerification() {
  const body = $("verify-body");
  clear(body);
  const view = state.view;
  if (!view) {
    body.append(
      el("p", {
        class: "empty",
        text:
          "A receipt is content-addressed, so it can be checked by anyone " +
          "holding it. Open one and this pane shows what held.",
      })
    );
    return;
  }

  const v = view.verification;
  body.append(
    el(
      "div",
      { class: `verdict-banner ${v.verdict}` },
      el("span", { class: "verdict-headline", text: v.headline })
    )
  );

  for (const check of v.checks) {
    const card = el(
      "div",
      { class: `check-card ${check.state}` },
      el(
        "div",
        { class: "check-head" },
        el("span", { class: "check-label", text: check.label }),
        el("span", {
          class: `check-pill ${check.state}`,
          text: CHECK_STATE_LABEL[check.state] || check.state,
        })
      ),
      el("p", { class: "check-detail", text: check.detail })
    );
    if (check.expected || check.actual) {
      const dl = el("dl", { class: "report-kv tight" });
      if (check.expected) dl.append(el("dt", { text: "Claimed" }), el("dd", { class: "mono", text: check.expected }));
      if (check.actual) dl.append(el("dt", { text: "Computed" }), el("dd", { class: "mono", text: check.actual }));
      card.append(dl);
    }
    for (const key of ["missing", "tampered"]) {
      if (Array.isArray(check[key]) && check[key].length) {
        const ul = el("ul", { class: "check-list" });
        for (const id of check[key]) ul.append(el("li", { class: "mono", text: shortHash(id) }));
        card.append(ul);
      }
    }
    body.append(card);
  }

  // What the report was rendered against. A gap here is the reason a check
  // above said "not checked", so the two are read together.
  const res = view.resolution;
  const inputs = el("div", { class: "resolution" }, el("div", { class: "field-label", text: "Rendered against" }));
  const dl = el("dl", { class: "report-kv tight" });
  dl.append(
    el("dt", { text: "Facts" }),
    el("dd", {
      text: res.facts.state === "resolved" ? res.facts.source : res.facts.reason,
    }),
    el("dt", { text: "Pack" }),
    el("dd", {
      text:
        res.pack.state === "resolved"
          ? `${res.pack.source} (v${res.pack.version})`
          : res.pack.reason,
    })
  );
  inputs.append(dl);
  if (res.pack.state === "moved") {
    inputs.append(
      el("p", {
        class: "note warn",
        text:
          "Rule descriptions are omitted from the report above rather than " +
          "taken from the version now on disk: text this receipt's rules " +
          "never carried would read as if they had.",
      })
    );
  }
  body.append(inputs);

  body.append(renderDownloads(view));
}

function renderDownloads(view) {
  const wrap = el("div", { class: "downloads" }, el("div", { class: "field-label", text: "Export" }));
  if (!view.caseId) {
    wrap.append(
      el("p", {
        class: "muted",
        text:
          "Exports are served for receipts in the committed corpus. This one " +
          "came from outside it — you already hold the bytes.",
      })
    );
    return wrap;
  }
  const base = `/api/receipts/corpus/${encodeURIComponent(view.caseId)}`;
  const row = el("div", { class: "download-row" });
  for (const [href, label] of [
    [`${base}/bundle.json`, "Receipt + facts"],
    [`${base}/receipt.json`, "Receipt JSON"],
    [`${base}/report?format=md`, "Markdown"],
    [`${base}/report?format=pdf`, "PDF report"],
  ]) {
    row.append(el("a", { class: "ghost-btn small", href, text: label }));
  }
  wrap.append(row);
  wrap.append(
    el("p", {
      class: "muted",
      text:
        "The receipt alone verifies its own hash anywhere. The bundle adds " +
        "the facts it was adjudicated over, so it also replays anywhere — " +
        "which is the check this pane cannot run on a receipt that arrives " +
        "by itself.",
    })
  );
  return wrap;
}

/* ---------- opening a receipt ---------- */

function render() {
  renderPicker();
  renderReportHead();
  renderTabs();
  renderReportBody();
  renderVerification();
}

function announce(view) {
  const v = view.verification;
  if (v.verdict === "pass") setStatus("Verified", "ready");
  else if (v.verdict === "fail") setStatus("Verification failed", "error");
  else setStatus("Partly verified", "info");
}

async function openCase(caseId) {
  if (state.loading) return;
  state.loading = true;
  setStatus("Verifying…", "loading");
  try {
    const view = await getJSON(`/api/receipts/corpus/${encodeURIComponent(caseId)}`);
    state.view = view;
    state.caseId = caseId;
    state.tab = "report";
    location.hash = `case=${caseId}`;
    announce(view);
  } catch (err) {
    setStatus(err.message, "error");
  } finally {
    state.loading = false;
    render();
  }
}

/* Documents go to the server as the text the user gave us, never as objects
 * this file parsed and re-serialized. JavaScript has one number type: a
 * round trip through JSON.parse/JSON.stringify turns a fact's
 * `"score": 1.0` into `1`, which is a different canonical body and a
 * different content hash — so a viewer that re-serialized would report
 * every genuine fact as tampered with. It parses to *check* the input, and
 * sends the bytes. */
async function inspect(documents) {
  state.loading = true;
  setStatus("Verifying…", "loading");
  try {
    const view = await getJSON("/api/receipts/inspect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ documents }),
    });
    state.view = view;
    state.caseId = view.caseId;
    state.tab = "report";
    if (view.caseId) location.hash = `case=${view.caseId}`;
    else location.hash = "";
    announce(view);
    closeModal();
  } catch (err) {
    setStatus(err.message, "error");
    const err_node = $("paste-error");
    if (err_node) err_node.textContent = err.message;
  } finally {
    state.loading = false;
    render();
  }
}

/* ---------- paste modal ---------- */

function closeModal() {
  $("modal").hidden = true;
}

function parseDocuments(text) {
  const parsed = JSON.parse(text);
  return Array.isArray(parsed) ? parsed : [parsed];
}

function countReceipts(docs) {
  // A receipt carries receiptSha256; a grounded fact carries contentHash.
  // The server sorts the pile by the same test — this is only so the modal
  // can refuse an obviously wrong input before making a round trip.
  return docs.filter((d) => d && typeof d === "object" && "receiptSha256" in d).length;
}

function openPasteModal() {
  const modal = $("modal");
  $("modal-title").textContent = "Paste a receipt";
  const body = $("modal-body");
  clear(body);

  const area = el("textarea", {
    id: "paste-area",
    class: "text-input mono",
    rows: 14,
    placeholder: '{ "id": "urn:duly:receipt:sha256:…", "decision": { … } }',
    "aria-label": "Receipt JSON",
  });
  const factsArea = el("textarea", {
    id: "paste-facts",
    class: "text-input mono",
    rows: 6,
    placeholder: "[ … the GroundedFacts this receipt pinned … ]",
    "aria-label": "Input facts JSON",
  });
  const file = el("input", {
    type: "file",
    id: "paste-files",
    class: "text-input",
    accept: ".json,application/json",
    multiple: true,
    "aria-label": "Receipt and fact files",
  });
  const error = el("p", { id: "paste-error", class: "note error" });
  const summary = el("span", { class: "field-hint" });
  state.files = [];

  body.append(
    el("p", {
      class: "muted",
      text:
        "The receipt alone verifies its own hash. Add the facts it pinned to " +
        "unlock the evidence quotes and the replay check — a receipt pins " +
        "facts by hash, so it cannot supply them itself.",
    }),
    el("div", { class: "field" }, el("label", { for: "paste-area", text: "Receipt JSON" }), area),
    el(
      "div",
      { class: "field" },
      el("label", { for: "paste-facts", text: "Input facts (optional)" }),
      factsArea
    ),
    el(
      "div",
      { class: "field" },
      el("label", { for: "paste-files", text: "…or choose files" }),
      file,
      el("span", {
        class: "field-hint",
        text: "Receipts and facts are told apart by their own fields; drop them all in together.",
      }),
      summary
    ),
    error,
    el(
      "div",
      { class: "modal-actions" },
      el("button", { type: "button", class: "ghost-btn", text: "Cancel", onclick: closeModal }),
      el("button", { type: "button", class: "primary-btn", text: "Verify", onclick: submitPaste })
    )
  );

  // Chosen files are held as their own text and sent that way. They are
  // parsed here only to say something useful before the round trip — putting
  // a re-serialized copy into the textarea would be the very round trip this
  // file exists to avoid.
  file.addEventListener("change", async () => {
    error.textContent = "";
    state.files = [];
    try {
      let receipts = 0;
      for (const f of file.files) {
        const text = await f.text();
        receipts += countReceipts(parseDocuments(text));
        state.files.push(text);
      }
      if (!receipts) {
        error.textContent =
          "None of those files carries a receiptSha256 — no receipt among them.";
        state.files = [];
        return;
      }
      summary.textContent = `${plural(file.files.length, "file")} ready, ${plural(
        receipts,
        "receipt"
      )} among them.`;
    } catch (err) {
      state.files = [];
      error.textContent = `Could not read those files: ${err.message}`;
    }
  });

  modal.hidden = false;
  area.focus();
}

function submitPaste() {
  const error = $("paste-error");
  error.textContent = "";

  // Every blob is validated here and sent verbatim. The check is a courtesy —
  // it turns a 422 into an inline message — and the text is what travels.
  const blobs = [$("paste-area").value, $("paste-facts").value, ...state.files];
  const present = blobs.filter((text) => text && text.trim());
  if (!present.length) {
    error.textContent = "Paste a receipt, or choose the files it came in.";
    return;
  }
  let receipts = 0;
  for (const text of present) {
    try {
      receipts += countReceipts(parseDocuments(text));
    } catch (err) {
      error.textContent = `That is not valid JSON: ${err.message}`;
      return;
    }
  }
  if (!receipts) {
    error.textContent =
      "No receipt in there: a DecisionReceipt carries a receiptSha256 field.";
    return;
  }
  inspect(present);
}

/* ---------- boot ---------- */

/* Two deep-link forms, because a receipt is referred to two ways. A person
 * quoting the corpus has a case id; a log line has a hash and nothing else,
 * so `#sha=` resolves against the index already loaded rather than asking
 * the server the same question a second time. */
function deepLinkCase() {
  const hash = location.hash || "";
  const byCase = /(?:^|[#&])case=([^&]+)/.exec(hash);
  if (byCase) return decodeURIComponent(byCase[1]);
  const bySha = /(?:^|[#&])sha=([^&]+)/.exec(hash);
  if (bySha) {
    const needle = decodeURIComponent(bySha[1]).split(":").pop().toLowerCase();
    const matches = state.corpus.filter((r) => r.receiptSha256.startsWith(needle));
    if (matches.length === 1) return matches[0].caseId;
    state.filter = needle;
    const search = $("corpus-search");
    if (search) search.value = needle;
  }
  return null;
}

async function boot() {
  $("paste-btn").addEventListener("click", openPasteModal);
  $("modal-close").addEventListener("click", closeModal);
  $("modal").addEventListener("click", (event) => {
    if (event.target === $("modal")) closeModal();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !$("modal").hidden) closeModal();
  });

  const search = $("corpus-search");
  search.addEventListener("input", (event) => {
    state.filter = event.target.value;
    state.active = 0;
    openPicker();
  });
  search.addEventListener("focus", openPicker);
  search.addEventListener("blur", closePicker);
  search.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      movePick(1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      movePick(-1);
    } else if (event.key === "Enter") {
      const row = state.open ? state.matches[state.active] : null;
      if (row) {
        event.preventDefault();
        commitPick(row.caseId);
      }
    } else if (event.key === "Escape") {
      if (state.open) {
        event.stopPropagation();
        closePicker();
      }
    }
  });
  $("corpus-pack").addEventListener("change", (event) => {
    state.pack = event.target.value;
    state.active = 0;
    // Narrowing the pack while the field is idle should show what it narrowed
    // to, not silently change what a later search will return.
    if (document.activeElement === search) openPicker();
    else recomputeMatches();
  });
  window.addEventListener("hashchange", () => {
    const caseId = deepLinkCase();
    if (caseId && caseId !== state.caseId) openCase(caseId);
  });

  setStatus("Loading corpus…", "loading");
  try {
    const corpus = await getJSON("/api/receipts/corpus");
    state.corpus = corpus.cases;
    state.packs = corpus.packs;
  } catch (err) {
    setStatus(`Corpus unavailable: ${err.message}`, "error");
    render();
    return;
  }

  const select = $("corpus-pack");
  select.append(el("option", { value: "", text: "All packs" }));
  for (const pack of state.packs) select.append(el("option", { value: pack, text: pack }));
  recomputeMatches();

  const deep = deepLinkCase();
  if (deep) {
    await openCase(deep);
  } else {
    setStatus(`${state.corpus.length} receipts`, "ready");
    render();
    // A `#sha=` that matched several receipts (or none) left its needle in the
    // field. Show what it matched rather than a filtered box with no list.
    if (state.filter) openPicker();
  }
}

boot();
