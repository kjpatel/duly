/* duly rule studio — vanilla JS, no dependencies.
 *
 * Same discipline as app.js: every piece of server data reaches the page
 * through textContent, never innerHTML. The only markup this file writes is
 * markup it constructs itself.
 *
 * The editing model is deliberately thin. This file never *derives* pack
 * semantics — it renders the projection the server computed (which is computed
 * with the kernel's own expression parser) and posts whole packs back. So a
 * rule the studio cannot lay out as a table is still a rule the studio can
 * show and edit; it just says so instead of pretending the grid is complete.
 */
"use strict";

const state = {
  packs: [],
  capabilities: {},
  sessionNote: "",
  slug: null,
  detail: null,
  tab: "table",
  saving: false,
  expected: null,
  impact: null,
  prove: null,
  caseRun: null,
  caseForm: null,
  dmn: null,
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

function plural(count, singular, pluralForm = singular + "s") {
  return `${count} ${count === 1 ? singular : pluralForm}`;
}

function shortAttr(curie) {
  if (typeof curie !== "string") return "";
  const i = curie.indexOf(":");
  return i >= 0 ? curie.slice(i + 1) : curie;
}

function fmtValue(v) {
  if (v == null || typeof v !== "object") return String(v);
  if (v.kind === "money") return `${v.amount} ${v.currency}`;
  if (v.kind === "boolean") return v.value ? "true" : "false";
  return String(v.value);
}

function setStatus(text, mode = "ready") {
  const status = $("workspace-status");
  $("workspace-status-text").textContent = text;
  for (const cls of ["loading", "error", "info", "fixture"]) {
    status.classList.toggle(cls, mode === cls);
  }
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

async function api(path, options) {
  const res = await fetch(path, options);
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

function postJson(path, payload, method = "POST") {
  return api(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload || {}),
  });
}

/* ---------- boot ---------- */

async function init() {
  setStatus("Loading packs", "loading");
  const data = await api("/api/rules/packs");
  state.packs = data.packs;
  state.capabilities = data.capabilities;
  state.sessionNote = data.sessionNote;
  $("studio-note").textContent = data.sessionNote;
  $("new-pack-btn").addEventListener("click", openNewPackDialog);
  $("import-dmn-btn").addEventListener("click", () => {
    if (!state.slug) return;
    state.tab = "dmn";
    renderEditor();
  });
  $("modal-close").addEventListener("click", closeModal);
  $("modal").addEventListener("click", (event) => {
    if (event.target === $("modal")) closeModal();
  });
  renderPackList();
  renderCapabilities();
  // Deep links: ?pack=<slug>&tab=<view>. A rule argument usually happens in a
  // pull request, and "look at this table" is only a useful sentence if it can
  // carry a URL.
  const params = new URLSearchParams(window.location.search);
  const wanted = params.get("pack");
  const tab = params.get("tab");
  if (tab && TABS.some((t) => t.id === tab)) state.tab = tab;
  const start = state.packs.find((p) => p.slug === wanted) || state.packs[0];
  if (start) await selectPack(start.slug);
  else setStatus("No packs found", "error");
}

function syncLocation() {
  if (!state.slug) return;
  const params = new URLSearchParams({ pack: state.slug, tab: state.tab });
  window.history.replaceState(null, "", `/rules?${params.toString()}`);
}

function renderCapabilities() {
  const missing = [];
  if (!state.capabilities.kernel) missing.push("the kernel (nothing can be adjudicated)");
  if (!state.capabilities.impact) missing.push("golden impact analysis");
  if (!state.capabilities.prove) missing.push("static verification (optional z3: `uv sync --extra prove`)");
  if (!state.capabilities.dmn) missing.push("the DMN compiler");
  if (!state.capabilities.whatif) missing.push("the ad-hoc case tester");
  const node = $("capabilities");
  node.replaceChildren();
  if (!missing.length) {
    node.append("Every instrument is available in this deployment.");
    return;
  }
  node.append("Unavailable here: " + missing.join("; ") + ".");
}

async function refreshPackList() {
  const data = await api("/api/rules/packs");
  state.packs = data.packs;
  renderPackList();
}

function renderPackList() {
  const list = $("pack-list");
  list.replaceChildren();
  $("pack-count").textContent = plural(state.packs.length, "pack");
  for (const pack of state.packs) {
    const active = pack.slug === state.slug;
    list.append(
      el(
        "button",
        {
          class: "pack-card" + (active ? " active" : ""),
          type: "button",
          "aria-current": active ? "true" : null,
          onclick: () => selectPack(pack.slug),
        },
        el(
          "span",
          { class: "pack-card-top" },
          el("span", { class: "pack-name", text: pack.name }),
          pack.dirty ? el("span", { class: "dot-draft", title: "unsaved session draft" }) : null,
        ),
        el(
          "span",
          { class: "pack-meta" },
          el("span", { text: pack.version || "no version" }),
          el("span", { text: plural(pack.ruleCount, "rule") }),
          el("span", { text: plural(pack.decisionCount, "decision") }),
        ),
        el(
          "span",
          { class: "pack-meta muted" },
          el("span", { text: plural(pack.expectedCases, "declared case") }),
          el("span", { text: `${pack.goldenReceipts} golden receipts` }),
          !pack.committed ? el("span", { class: "tag-new", text: "session only" }) : null,
        ),
      ),
    );
  }
}

async function selectPack(slug) {
  setStatus("Loading pack", "loading");
  state.slug = slug;
  state.expected = null;
  state.impact = null;
  state.prove = null;
  state.caseRun = null;
  state.caseForm = null;
  try {
    state.detail = await api(`/api/rules/packs/${encodeURIComponent(slug)}`);
  } catch (err) {
    setStatus(err.message, "error");
    return;
  }
  renderPackList();
  renderAll();
  setStatus(state.detail.dirty ? "Draft — not written to disk" : "Ready",
            state.detail.dirty ? "info" : "ready");
}

function renderAll() {
  renderHeader();
  renderEditor();
  renderVerify();
}

function renderHeader() {
  const d = state.detail;
  $("editor-title").textContent = d.name;
  const bits = [d.version, d.ontology ? `${d.ontology}@${d.ontologyVersion}` : null,
                d.idPrefix ? `ids ${d.idPrefix}-*` : null].filter(Boolean);
  $("editor-subtitle").textContent = bits.join(" · ");
  $("draft-badge").hidden = !d.dirty;
}

/* ---------- draft mutation ---------- */

/* Every structured edit goes through here: clone the pack, let the caller
 * change it, send the whole thing. Whole-pack sends rather than patches
 * because the server's answer to "is this a legal pack" is about the pack,
 * not about the edit — a change that is fine in isolation and illegal in
 * context (a duplicate id, a broken override target) must fail here. */
async function mutate(fn, label) {
  if (state.saving) return;
  state.saving = true;
  setStatus(label || "Saving draft", "loading");
  const pack = clone(state.detail.pack);
  try {
    fn(pack);
  } catch (err) {
    state.saving = false;
    setStatus(err.message, "error");
    return;
  }
  try {
    state.detail = await postJson(
      `/api/rules/packs/${encodeURIComponent(state.slug)}/draft`, { pack }, "PUT",
    );
  } catch (err) {
    setStatus(err.message, "error");
    state.saving = false;
    return;
  }
  state.saving = false;
  // A change invalidates every previous verdict. Clearing them is the honest
  // move: a stale green "12 cases pass" beside an edited pack is a lie.
  state.expected = null;
  state.impact = null;
  state.prove = null;
  state.caseRun = null;
  await refreshPackList();
  renderAll();
  setStatus("Draft updated — nothing written to disk", "info");
}

function findRule(pack, ruleId) {
  const rule = (pack.rules || []).find((r) => r.id === ruleId);
  if (!rule) throw new Error(`Rule ${ruleId} is no longer in the pack`);
  return rule;
}

/* ---------- editor tabs ---------- */

const TABS = [
  { id: "table", label: "Decision tables" },
  { id: "rules", label: "Rules" },
  { id: "source", label: "pack.yaml" },
  { id: "dmn", label: "DMN import" },
];

function renderEditor() {
  syncLocation();
  const tabs = $("editor-tabs");
  tabs.replaceChildren();
  for (const tab of TABS) {
    tabs.append(
      el("button", {
        class: "tab" + (state.tab === tab.id ? " active" : ""),
        type: "button",
        role: "tab",
        "aria-selected": state.tab === tab.id ? "true" : "false",
        text: tab.label,
        onclick: () => {
          state.tab = tab.id;
          renderEditor();
        },
      }),
    );
  }
  const body = $("editor-body");
  body.replaceChildren();
  if (state.tab === "table") body.append(...renderTables());
  else if (state.tab === "rules") body.append(...renderRuleCards());
  else if (state.tab === "source") body.append(renderSource());
  else body.append(renderDmnPanel());
}

/* ---------- decision tables ---------- */

function tableLegend() {
  return el(
    "p",
    { class: "legend" },
    "A cell is a condition on one input. ",
    el("span", { class: "cell-any", text: "any" }),
    " means the rule binds the input but does not constrain it; ",
    el("span", { class: "cell-unbound", text: "—" }),
    " means the rule does not bind it at all, so the fact need not exist for the " +
      "rule to fire. That distinction is the one DMN authors trip on, and it " +
      "changes which cases a rule reaches.",
  );
}

function renderTables() {
  const tables = state.detail.tables || [];
  if (!tables.length) {
    return [el("p", { class: "empty", text: "This pack concludes nothing yet." })];
  }
  const nodes = [tableLegend()];
  for (const table of tables) {
    nodes.push(renderTable(table));
  }
  nodes.push(
    el(
      "p",
      { class: "legend" },
      "This grid is a view of the rule IR, not a DMN document: `duly_dmn` " +
        "compiles DMN into the IR and deliberately does not decompile. " +
        "Authoring through DMN is the import tab, which is the real one-way path.",
    ),
  );
  return nodes;
}

function renderTable(table) {
  const head = el(
    "div",
    { class: "table-head" },
    el(
      "div",
      {},
      el("div", { class: "table-attr", text: table.attribute }),
      el("div", {
        class: "table-question",
        text: table.question || (table.declared ? "" : "not a declared decision — an intermediate value"),
      }),
    ),
    el(
      "div",
      { class: "table-tags" },
      el(
        "span",
        {
          class: "table-policy",
          title:
            table.hitPolicy === "UNIQUE"
              ? "All rules sit at one priority, so they must be mutually exclusive"
              : "Rules sit at several priorities; the highest applicable one wins",
        },
        el("span", { class: "policy-label", text: "hit policy" }),
        el("span", { class: "policy-value", text: table.hitPolicy }),
      ),
      ...table.entityTypes.map((t) => el("span", { class: "tag subtle", text: t })),
    ),
  );

  const headRow = el(
    "tr",
    {},
    el("th", { class: "col-rule", text: "Rule" }),
    el("th", { class: "col-num", text: "Pri" }),
    el("th", { class: "col-when", text: "In force" }),
    ...table.columns.map((column) =>
      el(
        "th",
        { class: "col-input", title: `${column.kind} binding on ${column.ref}` },
        el("span", { class: "col-name", text: column.name }),
        el("span", { class: "col-ref", text: column.ref }),
        column.kind !== "attribute"
          ? el("span", { class: "col-kind", text: column.kind })
          : null,
      ),
    ),
    el("th", { class: "col-out", text: "⇒ " + shortAttr(table.attribute) }),
    el("th", { class: "col-cite", text: "Authority" }),
  );

  const rows = [];
  for (const row of table.rows) {
    rows.push(renderTableRow(table, row));
    if (row.cross.length) rows.push(renderCrossRow(table, row));
  }

  return el(
    "section",
    { class: "table-block" },
    head,
    el(
      "div",
      { class: "table-scroll" },
      el("table", { class: "decision-table" }, el("thead", {}, headRow), el("tbody", {}, rows)),
    ),
    el(
      "div",
      { class: "table-actions" },
      el("button", {
        class: "ghost-btn small",
        type: "button",
        text: "Add rule to this table",
        onclick: () => addRule(table),
      }),
    ),
  );
}

function renderTableRow(table, row) {
  const cells = table.columns.map((column, index) => renderCell(table, row, column, row.cells[index]));
  return el(
    "tr",
    { class: "rule-row" },
    el(
      "td",
      { class: "col-rule" },
      el("span", { class: "rule-id", text: row.ruleId }),
      row.overrides.length
        ? el("span", {
            class: "badge-override",
            title: "Authored exception: this rule defeats those ids",
            text: "overrides " + row.overrides.join(", "),
          })
        : null,
    ),
    el(
      "td",
      { class: "col-num" },
      el("input", {
        class: "cell-input num",
        type: "number",
        value: row.priority ?? 0,
        "aria-label": `priority of ${row.ruleId}`,
        onchange: (event) =>
          mutate((pack) => {
            findRule(pack, row.ruleId).priority = Number(event.target.value);
          }, "Changing priority"),
      }),
    ),
    el(
      "td",
      { class: "col-when" },
      el("span", { class: "eff", text: (row.effectiveFrom || "").slice(0, 10) }),
      el("span", { class: "eff muted", text: row.effectiveTo ? "→ " + row.effectiveTo.slice(0, 10) : "→ open" }),
    ),
    ...cells,
    el(
      "td",
      { class: "col-out" },
      el("input", {
        class: "cell-input out",
        type: "text",
        value: row.output,
        "aria-label": `conclusion of ${row.ruleId}`,
        onchange: (event) => setOutput(row.ruleId, event.target.value),
      }),
    ),
    el(
      "td",
      { class: "col-cite" },
      row.citationUrl
        ? el("a", { href: row.citationUrl, target: "_blank", rel: "noopener", text: row.citation })
        : el("span", { text: row.citation }),
      el("button", {
        class: "icon-btn tiny",
        type: "button",
        title: "Edit this rule in full",
        text: "✎",
        onclick: () => {
          state.tab = "rules";
          renderEditor();
          const card = document.getElementById("rule-" + row.ruleId);
          if (card) card.scrollIntoView({ block: "center" });
        },
      }),
    ),
  );
}

function renderCell(table, row, column, cell) {
  const inputs = [];
  // A cell can own more than one condition — a range guard is two — so each
  // input carries the slot it stands for. Without it every input in the cell
  // would rewrite the whole owned set, and editing one bound would delete the
  // other.
  const conditions = cell.conditions.length ? cell.conditions : [""];
  conditions.forEach((condition, slot) => {
    inputs.push(
      el("input", {
        class: "cell-input" + (cell.bound ? "" : " unbound"),
        type: "text",
        value: condition,
        placeholder: cell.bound ? "any" : "—",
        title: cell.bound
          ? `${column.name} is bound to ${column.ref}`
          : `${row.ruleId} does not bind ${column.ref}; typing a condition binds it, ` +
            "which also makes the fact required for this rule to fire",
        "aria-label":
          conditions.length > 1
            ? `${column.name} condition ${slot + 1} for ${row.ruleId}`
            : `${column.name} condition for ${row.ruleId}`,
        onchange: (event) => setCell(table, row, column, cell, slot, event.target.value),
      }),
    );
  });
  return el(
    "td",
    { class: "col-input" + (cell.bound ? "" : " is-unbound") },
    inputs,
    cell.bound && !cell.conditions.length
      ? el("button", {
          class: "icon-btn tiny",
          type: "button",
          title: `Unbind ${column.ref} from ${row.ruleId} — the rule stops requiring the fact`,
          text: "⊘",
          onclick: () => unbind(row.ruleId, column.name),
        })
      : null,
  );
}

function renderCrossRow(table, row) {
  return el(
    "tr",
    { class: "cross-row" },
    el("td", { class: "col-rule", text: "" }),
    el(
      "td",
      { colSpan: 4 + table.columns.length },
      el("span", {
        class: "cross-label",
        title:
          "This condition relates more than one input, so no single column owns it. " +
          "A DMN table cannot express it in a cell either — it is the shape of rule " +
          "the grid genuinely does not cover.",
        text: "cross-input",
      }),
      ...row.cross.map((condition, i) =>
        el("input", {
          class: "cell-input wide",
          type: "text",
          value: condition,
          "aria-label": `cross-input condition ${i + 1} for ${row.ruleId}`,
          onchange: (event) =>
            mutate((pack) => {
              const rule = findRule(pack, row.ruleId);
              const when = (rule.when || []).slice();
              when[row.crossIndices[i]] = event.target.value;
              rule.when = when.filter((w) => String(w).trim());
            }, "Editing condition"),
        }),
      ),
    ),
  );
}

/* Rewrite exactly the one `when` entry this input owns, in place, so an edit
 * in one column does not reshuffle the rest of the diff — and so a cell that
 * owns several conditions loses none of them. `slot` indexes into the cell's
 * own conditions; `cell.indices[slot]` is that condition's position in the
 * rule's `when` list, which is what the server computed it for. An empty cell
 * owns no position yet, so a value there appends. */
function setCell(table, row, column, cell, slot, text) {
  const value = text.trim();
  const position = cell.indices[slot];
  return mutate((pack) => {
    const rule = findRule(pack, row.ruleId);
    const when = (rule.when || []).slice();
    if (position === undefined) {
      if (value) when.push(value);
    } else if (value) {
      when[position] = value;
    } else {
      when.splice(position, 1);
    }
    if (when.length) rule.when = when;
    else delete rule.when;
    if (value && !cell.bound) {
      rule.given = rule.given || {};
      rule.given[column.name] = { [column.kind]: column.ref };
    }
  }, "Editing condition");
}

function unbind(ruleId, name) {
  return mutate((pack) => {
    const rule = findRule(pack, ruleId);
    if (rule.given) delete rule.given[name];
    if (rule.when) {
      rule.when = rule.when.filter((w) => !new RegExp(`\\b${name}\\b`).test(String(w)));
      if (!rule.when.length) delete rule.when;
    }
  }, "Removing binding");
}

/* The conclusion cell is typed by the rule's declared value kind: a literal
 * for booleans, an expression otherwise, which is how the IR distinguishes
 * "this rule concludes 45" from "this rule computes actual - disclosed". */
function setOutput(ruleId, text) {
  return mutate((pack) => {
    const rule = findRule(pack, ruleId);
    const value = rule.then.value || {};
    const kind = value.kind;
    if (kind === "boolean") {
      const lowered = text.trim().toLowerCase();
      if (lowered !== "true" && lowered !== "false") {
        throw new Error(`A boolean conclusion must be true or false, got ${text}`);
      }
      rule.then.value = { kind, value: lowered === "true" };
    } else if ("expr" in value) {
      rule.then.value = { ...value, expr: text.trim() };
    } else if (kind === "money") {
      rule.then.value = { ...value, amount: text.trim().split(/\s+/)[0] };
    } else {
      rule.then.value = { ...value, value: text.trim() };
    }
  }, "Editing conclusion");
}

function addRule(table) {
  const prefix = state.detail.idPrefix;
  if (!prefix) {
    setStatus("This pack declares no idPrefix, so the studio cannot name a new rule", "error");
    return;
  }
  const existing = new Set((state.detail.pack.rules || []).map((r) => r.id));
  const topic = shortAttr(table.attribute).replace(/[^A-Za-z]/g, "").slice(0, 6).toUpperCase() || "NEW";
  let id = "";
  for (let n = 1; n < 100; n += 1) {
    id = `${prefix}-${topic}-${String(n).padStart(2, "0")}`;
    if (!existing.has(id)) break;
  }
  const model = table.rows.length ? findRuleView(table.rows[table.rows.length - 1].ruleId) : null;
  return mutate((pack) => {
    const given = {};
    for (const type of table.entityTypes) given.subject = { entityType: type };
    const rule = {
      id,
      description: "TODO(verify) describe what this rule holds and why.",
      version: "1.0.0",
      priority: model ? model.priority : 100,
      citation: { text: "TODO(verify) not yet cited" },
      effectiveFrom: new Date().toISOString().slice(0, 10),
      given,
      then: {
        entity: Object.keys(given)[0] || "subject",
        attribute: table.attribute,
        value: model ? clone(model.thenValue) : { kind: "boolean", value: true },
      },
    };
    pack.rules = (pack.rules || []).concat([rule]);
  }, "Adding rule");
}

function findRuleView(ruleId) {
  const rule = (state.detail.pack.rules || []).find((r) => r.id === ruleId);
  if (!rule) return null;
  return { priority: rule.priority, thenValue: rule.then.value };
}

/* ---------- rule cards ---------- */

function field(label, input, hint) {
  return el(
    "label",
    { class: "field" },
    el("span", { class: "field-label", text: label }),
    input,
    hint ? el("span", { class: "field-hint", text: hint }) : null,
  );
}

function textField(label, value, onCommit, hint, type = "text") {
  return field(
    label,
    el("input", {
      class: "text-input",
      type,
      value: value ?? "",
      onchange: (event) => onCommit(event.target.value),
    }),
    hint,
  );
}

function renderRuleCards() {
  const rules = state.detail.rules || [];
  if (!rules.length) return [el("p", { class: "empty", text: "This pack has no rules." })];
  return rules.map((rule) => renderRuleCard(rule));
}

function renderRuleCard(rule) {
  const id = rule.id;
  const set = (fn, label) => (value) => mutate((pack) => fn(findRule(pack, id), value), label);
  return el(
    "section",
    { class: "rule-card", id: "rule-" + id },
    el(
      "div",
      { class: "rule-card-head" },
      el("span", { class: "rule-id", text: id }),
      el("span", { class: "tag subtle", text: "v" + (rule.version || "?") }),
      el("span", { class: "tag subtle", text: "priority " + rule.priority }),
      rule.goldenReceipts
        ? el("span", {
            class: "tag receipts",
            title:
              "Committed golden receipts citing this id. Rule ids are permanent " +
              "because they are inside receipts that already shipped.",
            text: `${rule.goldenReceipts} receipts`,
          })
        : null,
      rule.todoVerify ? el("span", { class: "tag warn", text: "TODO(verify)" }) : null,
      el("span", { class: "spacer" }),
      el("button", {
        class: "ghost-btn small",
        type: "button",
        text: "Duplicate",
        onclick: () => duplicateRule(id),
      }),
      el("button", {
        class: "ghost-btn small danger",
        type: "button",
        text: "Delete",
        onclick: () => deleteRule(id),
      }),
    ),
    el(
      "div",
      { class: "rule-grid" },
      textField("Description", rule.description, set((r, v) => { r.description = v; }, "Editing description")),
      textField("Version", rule.version, set((r, v) => { r.version = v; }, "Editing version")),
      textField("Priority", rule.priority, set((r, v) => { r.priority = Number(v); }, "Editing priority"), null, "number"),
      textField("Effective from", (rule.effectiveFrom || "").slice(0, 10),
        set((r, v) => { r.effectiveFrom = v; }, "Editing effective window"), null, "date"),
      textField("Effective to", (rule.effectiveTo || "").slice(0, 10),
        set((r, v) => { if (v) r.effectiveTo = v; else delete r.effectiveTo; }, "Editing effective window"),
        "Empty means open-ended", "date"),
      textField("Citation", rule.citation.text,
        set((r, v) => { r.citation = { ...r.citation, text: v }; }, "Editing citation"),
        "Every rule cites its authority, or says TODO(verify) naming what is unconfirmed"),
      textField("Citation URL", rule.citation.url || "",
        set((r, v) => {
          const citation = { ...r.citation };
          if (v) citation.url = v; else delete citation.url;
          r.citation = citation;
        }, "Editing citation")),
    ),
    el(
      "div",
      { class: "rule-sub" },
      el("div", { class: "field-label", text: "Given (bindings)" }),
      el(
        "div",
        { class: "binding-list" },
        ...rule.given.map((binding) =>
          el(
            "div",
            { class: "binding" },
            el("code", { text: binding.name }),
            el("span", { class: "arrow", text: "←" }),
            el("span", { class: "tag subtle", text: binding.kind }),
            el("code", { text: binding.ref }),
          ),
        ),
      ),
    ),
    el(
      "div",
      { class: "rule-sub" },
      el("div", { class: "field-label", text: "When (all must hold)" }),
      ...(rule.when.length
        ? rule.when.map((condition, index) =>
            el("input", {
              class: "text-input mono",
              type: "text",
              value: condition,
              "aria-label": `condition ${index + 1} of ${id}`,
              onchange: (event) =>
                mutate((pack) => {
                  const target = findRule(pack, id);
                  const when = target.when.slice();
                  if (event.target.value.trim()) when[index] = event.target.value.trim();
                  else when.splice(index, 1);
                  if (when.length) target.when = when;
                  else delete target.when;
                }, "Editing condition"),
            }),
          )
        : [el("p", { class: "muted", text: "No guards — this rule applies whenever its bindings resolve." })]),
      el("button", {
        class: "ghost-btn small",
        type: "button",
        text: "Add condition",
        onclick: () =>
          mutate((pack) => {
            const target = findRule(pack, id);
            target.when = (target.when || []).concat(["true"]);
          }, "Adding condition"),
      }),
    ),
    el(
      "div",
      { class: "rule-sub" },
      el("div", { class: "field-label", text: "Then" }),
      el(
        "p",
        { class: "conclusion" },
        el("code", { text: rule.then.entity }),
        " . ",
        el("code", { text: rule.then.attribute }),
        " = ",
        el("code", { text: rule.then.display }),
        el("span", { class: "tag subtle", text: rule.then.kind || "?" }),
      ),
      rule.overrides.length
        ? el(
            "p",
            { class: "overrides" },
            "overrides ",
            el("code", { text: rule.overrides.join(", ") }),
            el("span", {
              class: "muted",
              text:
                " — an authored exception, or a workaround for a disjointness the " +
                "validator cannot prove. Run prove to find out which.",
            }),
          )
        : null,
    ),
  );
}

function duplicateRule(ruleId) {
  return mutate((pack) => {
    const source = findRule(pack, ruleId);
    const copy = clone(source);
    const existing = new Set(pack.rules.map((r) => r.id));
    const base = String(source.id).replace(/-\d+$/, "");
    for (let n = 1; n < 100; n += 1) {
      const candidate = `${base}-${String(n).padStart(2, "0")}`;
      if (!existing.has(candidate)) {
        copy.id = candidate;
        break;
      }
    }
    pack.rules = pack.rules.concat([copy]);
  }, "Duplicating rule");
}

function deleteRule(ruleId) {
  const view = (state.detail.rules || []).find((r) => r.id === ruleId);
  const warning = view && view.goldenReceipts
    ? `${ruleId} is cited by ${view.goldenReceipts} committed golden receipt(s). ` +
      "Deleting it will not change them — they are historical records — but every " +
      "replay of those cases under this pack will now decide without it. Continue?"
    : `Delete ${ruleId} from the draft?`;
  if (!window.confirm(warning)) return Promise.resolve();
  return mutate((pack) => {
    pack.rules = pack.rules.filter((r) => r.id !== ruleId);
    for (const rule of pack.rules) {
      if (rule.overrides) {
        rule.overrides = rule.overrides.filter((o) => o !== ruleId);
        if (!rule.overrides.length) delete rule.overrides;
      }
    }
  }, "Deleting rule");
}

/* ---------- pack.yaml source ---------- */

function renderSource() {
  const area = el("textarea", {
    class: "source-editor",
    spellcheck: false,
    value: state.detail.yaml,
    "aria-label": "pack.yaml source",
  });
  const status = el("p", { class: "muted", text: "" });
  return el(
    "div",
    { class: "source-pane" },
    el(
      "p",
      { class: "legend" },
      "Editing the source is the lossless path: comments survive. Structured " +
        "edits in the other tabs re-emit the pack from the IR, which drops YAML " +
        "comments — the diff in the Verify pane shows exactly what that costs.",
    ),
    area,
    el(
      "div",
      { class: "row-actions" },
      el("button", {
        class: "primary-btn",
        type: "button",
        text: "Apply as draft",
        onclick: async () => {
          setStatus("Applying source", "loading");
          try {
            state.detail = await postJson(
              `/api/rules/packs/${encodeURIComponent(state.slug)}/draft`,
              { yaml: area.value }, "PUT",
            );
          } catch (err) {
            status.textContent = err.message;
            setStatus("Source rejected", "error");
            return;
          }
          state.expected = null;
          state.impact = null;
          state.prove = null;
          await refreshPackList();
          renderAll();
          setStatus("Draft updated — nothing written to disk", "info");
        },
      }),
      el("button", {
        class: "ghost-btn",
        type: "button",
        text: "Reset editor",
        onclick: () => { area.value = state.detail.yaml; status.textContent = ""; },
      }),
    ),
    status,
  );
}

/* ---------- DMN import ---------- */

function renderDmnPanel() {
  const wrap = el("div", { class: "dmn-pane" });
  wrap.append(
    el(
      "p",
      { class: "legend" },
      "A DMN 1.3+ decision table compiles into the rule IR, and the kernel " +
        "cannot tell the result from a hand-written pack. Every row needs " +
        "duly:ruleId, duly:citation and duly:effectiveFrom annotations: the " +
        "compiler will not invent an id, an authority or a date for you.",
    ),
  );
  if (!state.capabilities.dmn) {
    wrap.append(el("p", { class: "empty", text: "duly_dmn is not importable in this deployment." }));
    return wrap;
  }

  const area = el("textarea", {
    class: "source-editor",
    spellcheck: false,
    placeholder: "Paste a .dmn document here, or load one of the committed examples below.",
    "aria-label": "DMN XML",
  });
  const result = el("div", { class: "dmn-result" });
  const examples = el("div", { class: "example-row" });

  api("/api/rules/dmn/examples").then((data) => {
    examples.replaceChildren(el("span", { class: "field-label", text: "Committed examples" }));
    for (const example of data.examples) {
      examples.append(
        el("button", {
          class: "ghost-btn small" + (example.refusal ? " refusal" : ""),
          type: "button",
          title: example.refusal
            ? "One minimal broken document per refusal class — watch it refuse"
            : example.path,
          text: example.name,
          onclick: () => compileDmn({ path: example.path }, area, result),
        }),
      );
    }
  });

  wrap.append(
    examples,
    area,
    el(
      "div",
      { class: "row-actions" },
      el("button", {
        class: "primary-btn",
        type: "button",
        text: "Compile",
        onclick: () => compileDmn({ xml: area.value }, area, result),
      }),
    ),
    result,
  );
  return wrap;
}

async function compileDmn(source, area, result) {
  setStatus("Compiling DMN", "loading");
  let data;
  try {
    data = await postJson("/api/rules/dmn/compile", source);
  } catch (err) {
    setStatus(err.message, "error");
    return;
  }
  if (data.xml && source.path) area.value = data.xml;
  result.replaceChildren();
  if (!data.ok) {
    result.append(
      el("div", { class: "verdict-card bad" },
        el("div", { class: "verdict-title", text: "Refused" }),
        el("pre", { class: "pre", text: data.error })),
      el("p", { class: "muted", text:
        "A refusal is the product, not a failure: it names the decision, the row " +
        "and the cell, and it is what stops a rule the IR cannot express from " +
        "being silently approximated into one it can." }),
    );
    setStatus("DMN refused", "info");
    return;
  }
  const slugInput = el("input", {
    class: "text-input",
    type: "text",
    value: (data.name || "imported").replace(/[^a-z0-9-]/gi, "-").toLowerCase(),
    "aria-label": "draft slug",
  });
  result.append(
    el("div", { class: "verdict-card good" },
      el("div", { class: "verdict-title",
        text: `Compiled ${plural(data.ruleCount, "rule")} across ${plural(data.decisionCount, "decision")}` }),
      el("p", { class: "muted", text: "Validated by the kernel's own pack validator before it was returned." })),
    el("pre", { class: "pre scroll", text: data.yaml }),
    el("div", { class: "row-actions" },
      field("Adopt as draft named", slugInput),
      el("button", {
        class: "primary-btn",
        type: "button",
        text: "Adopt",
        onclick: async () => {
          try {
            state.detail = await postJson("/api/rules/dmn/adopt",
              { slug: slugInput.value, xml: source.xml, path: source.path });
          } catch (err) {
            setStatus(err.message, "error");
            return;
          }
          state.slug = state.detail.slug;
          state.tab = "table";
          await refreshPackList();
          renderAll();
          setStatus("Compiled pack adopted as a session draft", "info");
        },
      })),
  );
  setStatus("DMN compiled", "ready");
}

/* ---------- verify rail ---------- */

function section(title, subtitle, ...body) {
  return el(
    "section",
    { class: "verify-section" },
    el("div", { class: "section-heading" },
      el("div", {},
        el("div", { class: "field-label", text: title }),
        subtitle ? el("p", { text: subtitle }) : null)),
    ...body,
  );
}

function renderVerify() {
  const body = $("verify-body");
  body.replaceChildren();
  body.append(
    renderValidation(),
    renderExpectedSection(),
    renderCaseSection(),
    renderImpactSection(),
    renderProveSection(),
    renderDiffSection(),
    renderExportSection(),
  );
}

function renderValidation() {
  const v = state.detail.validation;
  let card;
  if (v.ok === null) card = el("div", { class: "verdict-card", text: v.note });
  else if (v.ok) {
    card = el("div", { class: "verdict-card good" },
      el("div", { class: "verdict-title", text: "The kernel accepts this pack" }),
      el("p", { class: "muted", text:
        "Structure, expressions, effective windows, rule-id convention, and every " +
        "same-priority overlap either proven disjoint or explicitly overridden." }));
  } else {
    card = el("div", { class: "verdict-card bad" },
      el("div", { class: "verdict-title", text: "The kernel refuses this pack" }),
      el("pre", { class: "pre", text: v.error }),
      el("p", { class: "muted", text: "The draft is kept — an invalid intermediate state is a normal step in editing." }));
  }
  return section("Validation", "Live, on every edit", card);
}

function renderExpectedSection() {
  const run = el("button", {
    class: "primary-btn",
    type: "button",
    text: `Run ${plural(state.detail.expectedCases, "declared case")}`,
    disabled: !state.detail.expectedCases,
    onclick: async () => {
      setStatus("Running declared cases", "loading");
      try {
        state.expected = await postJson(`/api/rules/packs/${encodeURIComponent(state.slug)}/test/expected`, {});
      } catch (err) {
        setStatus(err.message, "error");
        return;
      }
      renderVerify();
      setStatus(state.expected.failed ? "Declared cases failing" : "Declared cases pass",
                state.expected.failed ? "error" : "ready");
    },
  });
  const nodes = [run];
  if (!state.detail.expectedCases) {
    nodes.push(el("p", { class: "muted", text:
      "This pack declares no outcomes, so nothing here can catch it breaking. " +
      "expected.yaml is the pack's own test suite (rulepacks/README.md)." }));
  }
  const result = state.expected;
  if (result) {
    if (result.note) nodes.push(el("p", { class: "muted", text: result.note }));
    nodes.push(el("p", { class: result.failed ? "result-line bad" : "result-line good",
      text: `${result.passed} passing, ${result.failed} failing` }));
    for (const item of result.cases) {
      nodes.push(
        el("div", { class: "case-row " + (item.ok ? "good" : "bad") },
          el("span", { class: "case-mark", text: item.ok ? "✓" : "×" }),
          el("div", {},
            el("div", { class: "case-name", text: item.name }),
            item.asOfEffective
              ? el("div", { class: "muted", text: `${item.question} at ${item.asOfEffective}` })
              : null,
            ...item.failures.map((f) => el("pre", { class: "pre", text: f })))),
      );
    }
  }
  return section("Declared cases", "expected.yaml — what CI runs", ...nodes);
}

function renderCaseSection() {
  if (!state.capabilities.whatif) {
    return section("Try a case", null,
      el("p", { class: "muted", text: "The ad-hoc tester needs duly_whatif for fact substitution." }));
  }
  const sets = state.detail.factSets || [];
  if (!sets.length) {
    return section("Try a case", null,
      el("p", { class: "muted", text:
        "No fact set is wired to this pack yet — a declared case's factsFrom or a " +
        "golden case pointing at it would give the tester something to start from." }));
  }
  if (!state.caseForm) {
    const first = sets[0];
    const questions = (state.detail.decisions || []).map((d) => d.attribute).filter(Boolean);
    state.caseForm = {
      factsPath: first.factsPath,
      asOfEffective: first.asOfEffective || "",
      attribute: first.question && questions.includes(first.question) ? first.question : questions[0],
      overrides: {},
    };
  }
  const form = state.caseForm;

  const setSelect = el("select", { class: "text-input",
    onchange: (event) => {
      const chosen = sets.find((s) => s.factsPath === event.target.value);
      form.factsPath = chosen.factsPath;
      if (chosen.asOfEffective) form.asOfEffective = chosen.asOfEffective;
      form.overrides = {};
      state.caseRun = null;
      renderVerify();
    } });
  for (const s of sets) {
    setSelect.append(el("option", { value: s.factsPath, text: s.label, selected: s.factsPath === form.factsPath }));
  }

  const questionSelect = el("select", { class: "text-input",
    onchange: (event) => { form.attribute = event.target.value; runCase(); } });
  for (const decision of state.detail.decisions || []) {
    if (!decision.attribute) continue;
    questionSelect.append(el("option", {
      value: decision.attribute,
      text: decision.question || decision.attribute,
      selected: decision.attribute === form.attribute,
    }));
  }

  const nodes = [
    field("Fact set", setSelect),
    field("Question", questionSelect),
    textField("As of (effective)", form.asOfEffective,
      (value) => { form.asOfEffective = value; runCase(); }, null, "date"),
    el("button", { class: "primary-btn", type: "button", text: "Run this case", onclick: runCase }),
  ];

  const run = state.caseRun;
  if (run) {
    nodes.push(el("div", { class: "field-label", text: "Inputs — change one and re-run" }));
    for (const input of run.inputs) {
      const current = form.overrides[input.attribute] ?? fmtValue(input.value);
      nodes.push(
        el("div", { class: "input-row" },
          el("code", { class: "input-attr", text: shortAttr(input.attribute), title: input.attribute }),
          el("input", { class: "text-input mono small", type: "text", value: current,
            "aria-label": input.attribute,
            onchange: (event) => {
              const raw = event.target.value.trim();
              if (raw && raw !== fmtValue(input.value)) form.overrides[input.attribute] = raw;
              else delete form.overrides[input.attribute];
              runCase();
            } }),
          el("span", { class: "tag subtle", text: input.value.kind })),
      );
    }
    if (run.error) {
      nodes.push(el("div", { class: "verdict-card bad" },
        el("div", { class: "verdict-title", text: "No decision" }),
        el("pre", { class: "pre", text: run.error })));
    } else if (run.decision) {
      // Deliberately untinted: green would read as "this is the good answer",
      // and the studio has no opinion about whether a notice is compliant.
      // Whether the draft *moved* the answer is the comparison row's job.
      nodes.push(el("div", { class: "verdict-card" },
        el("div", { class: "verdict-title", text: fmtValue(run.decision.value) }),
        el("p", { class: "muted", text: run.decision.attribute })));
      nodes.push(el("div", { class: "field-label", text: "Rules fired" }));
      for (const fired of run.rulesFired) {
        nodes.push(el("div", { class: "fired-row" },
          el("code", { text: fired.ruleId }),
          fired.defeated.length
            ? el("span", { class: "badge-defeat", text: "defeats " + fired.defeated.join(", ") })
            : null));
      }
      for (const entry of run.abstentions) {
        nodes.push(el("div", { class: "case-row warn" },
          el("span", { class: "case-mark", text: "!" }),
          el("div", {},
            el("div", { class: "case-name", text: "abstained: " + (entry.reason || "") }),
            el("div", { class: "muted", text: entry.attribute || "" }))));
      }
    }
    if (run.baseline) {
      nodes.push(el("div", { class: "case-row " + (run.changed ? "bad" : "") },
        el("span", { class: "case-mark", text: run.changed ? "≠" : "=" }),
        el("div", {},
          el("div", { class: "case-name",
            text: run.changed ? "Your draft changes this case" : "Same answer as the committed pack" }),
          el("div", { class: "muted",
            text: `committed: ${run.baseline.error || fmtValue(run.baseline.value)}` }))));
    }
  }
  return section("Try a case", "One case, by hand, under the draft", ...nodes);
}

async function runCase() {
  const form = state.caseForm;
  if (!form || !form.attribute || !form.asOfEffective) return;
  setStatus("Adjudicating", "loading");
  try {
    state.caseRun = await postJson(`/api/rules/packs/${encodeURIComponent(state.slug)}/test/case`, {
      factsPath: form.factsPath,
      asOfEffective: form.asOfEffective,
      attribute: form.attribute,
      overrides: form.overrides,
    });
  } catch (err) {
    setStatus(err.message, "error");
    return;
  }
  renderVerify();
  setStatus("Case adjudicated", "ready");
}

function renderImpactSection() {
  if (!state.capabilities.impact) {
    return section("Golden impact", null,
      el("p", { class: "muted", text: "The golden corpus or duly_assurance is unavailable here." }));
  }
  const nodes = [
    el("button", { class: "primary-btn", type: "button",
      text: "Re-adjudicate the golden corpus",
      disabled: !state.detail.committed,
      onclick: async () => {
        setStatus("Running impact analysis", "loading");
        try {
          state.impact = await postJson(`/api/rules/packs/${encodeURIComponent(state.slug)}/impact`, {});
        } catch (err) {
          setStatus(err.message, "error");
          return;
        }
        renderVerify();
        setStatus(state.impact.flipCount ? `${state.impact.flipCount} decisions flip` : "No decisions flip",
                  state.impact.flipCount ? "info" : "ready");
      } }),
  ];
  if (!state.detail.committed) {
    nodes.push(el("p", { class: "muted", text:
      "Impact compares a draft against committed golden receipts; this pack has no committed side yet." }));
  } else if (!state.detail.dirty) {
    nodes.push(el("p", { class: "muted", text:
      "No draft yet — running this now measures the committed pack against itself, which should be zero." }));
  }
  const report = state.impact;
  if (report) {
    nodes.push(el("p", { class: report.flipCount ? "result-line bad" : "result-line good", text: report.summary }));
    nodes.push(el("p", { class: "muted", text: report.note }));
    for (const flip of report.flips) {
      nodes.push(el("div", { class: "case-row bad" },
        el("span", { class: "case-mark", text: "≠" }),
        el("div", {},
          el("div", { class: "case-name", text: flip.caseId }),
          el("div", { class: "muted",
            text: `${flip.before.valueDisplay} → ${flip.after.valueDisplay}` }),
          el("div", { class: "muted",
            text: (flip.after.error || flip.after.rulesFired.map((r) => r.ruleId).join(", ")) }))));
    }
    for (const change of report.reasoningChanges) {
      nodes.push(el("div", { class: "case-row warn" },
        el("span", { class: "case-mark", text: "~" }),
        el("div", {},
          el("div", { class: "case-name", text: change.caseId }),
          el("div", { class: "muted", text: "same answer, different reasoning" }))));
    }
  }
  return section("Golden impact", "The only instrument that catches drift", ...nodes);
}

function renderProveSection() {
  if (!state.capabilities.prove) {
    return section("Static verification", null,
      el("p", { class: "muted", text:
        "Needs the optional z3 solver: `uv sync --extra prove`. Without it the " +
        "kernel's syntactic disjointness check still runs on every edit — this " +
        "panel is the stronger, solver-backed one." }));
  }
  const nodes = [
    el("button", { class: "primary-btn", type: "button", text: "Prove", onclick: async () => {
      setStatus("Proving", "loading");
      try {
        state.prove = await postJson(`/api/rules/packs/${encodeURIComponent(state.slug)}/prove`, {});
      } catch (err) {
        setStatus(err.message, "error");
        return;
      }
      renderVerify();
      setStatus("Proof run complete", "ready");
    } }),
  ];
  const result = state.prove;
  if (result && result.available) {
    const report = result.report;
    const unproved = (report.pairs || []).filter((p) => p.verdict !== "PROVED-DISJOINT");
    nodes.push(el("p", { class: unproved.length ? "result-line warn" : "result-line good",
      text: `${(report.pairs || []).length} same-priority pairs checked, ${unproved.length} not proved disjoint` }));
    for (const pair of unproved) {
      nodes.push(el("div", { class: "case-row warn" },
        el("span", { class: "case-mark", text: "?" }),
        el("div", {},
          el("div", { class: "case-name", text: pair.rules.join(" / ") }),
          el("div", { class: "muted", text: pair.reason || pair.verdict }))));
    }
    const uncovered = (report.coverage || []).filter((c) => !c.covered);
    if (uncovered.length) {
      nodes.push(el("p", { class: "muted",
        text: `${uncovered.length} input region(s) no rule covers.` }));
    }
    if (result.equivalence) nodes.push(...renderEquivalence(result.equivalence));
  }
  return section("Static verification", "Solver-backed, over the whole input space", ...nodes);
}

function renderEquivalence(eq) {
  const nodes = [el("div", { class: "field-label", text: "Draft vs committed" })];
  if (eq.error) {
    nodes.push(el("p", { class: "muted", text: eq.error }));
    return nodes;
  }
  if (eq.onlyDraft.length) {
    nodes.push(el("p", { class: "muted", text: "only in the draft: " + eq.onlyDraft.join(", ") }));
  }
  if (eq.onlyCommitted.length) {
    nodes.push(el("p", { class: "muted", text: "only in the committed pack: " + eq.onlyCommitted.join(", ") }));
  }
  for (const decision of eq.decisions) {
    const same = decision.verdict === "PROVED-EQUIVALENT";
    nodes.push(
      el("div", { class: "case-row " + (same ? "good" : "bad") },
        el("span", { class: "case-mark", text: same ? "=" : "≠" }),
        el("div", {},
          el("div", { class: "case-name", text: decision.attribute }),
          el("div", { class: "muted", text: decision.reason || decision.verdict }),
          !same && decision.committedValue !== null
            ? el("div", { class: "muted",
                text: `committed ${decision.committedValue} · draft ${decision.draftValue}` })
            : null,
          ...decision.witness.map(([key, value]) =>
            el("div", { class: "witness", text: `${key} = ${value}` })))),
    );
  }
  if (eq.trace && eq.trace.verdict !== "PROVED-EQUIVALENT") {
    nodes.push(
      el("div", { class: "case-row warn" },
        el("span", { class: "case-mark", text: "~" }),
        el("div", {},
          el("div", { class: "case-name", text: "Receipts differ even where the answer does not" }),
          ...(eq.trace.differences || []).map((d) => el("div", { class: "muted", text: d })))),
    );
  }
  return nodes;
}

function renderDiffSection() {
  const diff = state.detail.diff || {};
  const semantic = diff.semantic || [];
  const file = diff.file || [];
  if (!semantic.length && !file.length) return el("div");
  const fileBlock = el("pre", { class: "pre diff scroll", text: file.join("") });
  fileBlock.hidden = true;
  return section(
    "Diff", "What changed, and what you would be committing",
    semantic.length
      ? el("pre", { class: "pre diff scroll", text: semantic.join("") })
      : el("p", { class: "muted", text: "No semantic change — formatting or comments only." }),
    el("button", {
      class: "ghost-btn small",
      type: "button",
      text: `Show the file diff (${plural(file.length, "line")})`,
      onclick: (event) => {
        fileBlock.hidden = !fileBlock.hidden;
        event.target.textContent = fileBlock.hidden
          ? `Show the file diff (${plural(file.length, "line")})`
          : "Hide the file diff";
      },
    }),
    el("p", { class: "muted", text:
      "The first diff normalises both sides through the emitter, so it shows " +
      "the change in meaning. The file diff is what git would see — for a " +
      "structured edit that includes every YAML comment the re-emission drops." }),
    fileBlock,
  );
}

function renderExportSection() {
  const slug = encodeURIComponent(state.slug);
  return section("Export", state.sessionNote,
    el("div", { class: "row-actions" },
      el("a", { class: "download-btn", href: `/api/rules/packs/${slug}/pack.yaml`, text: "pack.yaml" }),
      el("a", { class: "download-btn", href: `/api/rules/packs/${slug}/bundle`, text: "Pack bundle (zip)" }),
      state.detail.dirty
        ? el("button", { class: "ghost-btn danger", type: "button", text: "Discard draft",
            onclick: async () => {
              if (!window.confirm("Discard this session draft?")) return;
              await api(`/api/rules/packs/${slug}/draft`, { method: "DELETE" });
              await refreshPackList();
              const survivor = state.packs.find((p) => p.slug === state.slug) || state.packs[0];
              await selectPack(survivor.slug);
            } })
        : null),
    el("p", { class: "muted", text:
      "A shipped pack also needs declared cases, a golden-corpus generator " +
      "template, and ontology coverage — the bundle carries a NEXT-STEPS note " +
      "listing them." }));
}

/* ---------- new pack dialog ---------- */

function openModal(title, body) {
  $("modal-title").textContent = title;
  $("modal-body").replaceChildren(body);
  $("modal").hidden = false;
}

function closeModal() {
  $("modal").hidden = true;
}

function openNewPackDialog() {
  const slug = el("input", { class: "text-input", type: "text", placeholder: "my-pack" });
  const name = el("input", { class: "text-input", type: "text", placeholder: "my-pack" });
  const prefix = el("input", { class: "text-input", type: "text", placeholder: "MYP" });
  const description = el("input", { class: "text-input", type: "text" });
  const error = el("p", { class: "muted" });
  openModal(
    "New rule pack",
    el("div", { class: "modal-form" },
      el("p", { class: "legend", text:
        "The skeleton starts with the conventions a new pack most often gets " +
        "wrong: an idPrefix, a convention-shaped rule id, an explicit " +
        "TODO(verify) where the citation belongs, and decision phrasing so a " +
        "non-boolean answer never renders as a raw CURIE." }),
      field("Directory slug", slug, "becomes rulepacks/<slug>/ when you commit it"),
      field("Pack name", name),
      field("Rule id prefix", prefix, "every new rule id joins this family"),
      field("Description", description),
      error,
      el("div", { class: "row-actions" },
        el("button", { class: "primary-btn", type: "button", text: "Create draft", onclick: async () => {
          try {
            state.detail = await postJson("/api/rules/packs", {
              slug: slug.value.trim(),
              name: name.value.trim() || slug.value.trim(),
              idPrefix: prefix.value.trim(),
              description: description.value.trim(),
            });
          } catch (err) {
            error.textContent = err.message;
            return;
          }
          closeModal();
          state.slug = state.detail.slug;
          state.tab = "rules";
          await refreshPackList();
          renderAll();
          setStatus("Draft pack created — session only", "info");
        } }))),
  );
}

init().catch((err) => setStatus(err.message, "error"));
