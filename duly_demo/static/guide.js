/* duly demo — the first-run orientation strip, shared by all four pages.
 *
 * Every page opens onto three dense panes of vocabulary this repo uses
 * precisely and nothing else does. The strip is the ladder up to that: three
 * steps, in the order a newcomer should read the page, dismissable and
 * re-openable. It deliberately does not explain the vocabulary itself — that
 * belongs beside each term, not in a wall of text at the top.
 *
 * Steps only, no lead line. Each page already carries an h1 and a subtitle
 * doing orientation work an inch above this strip, so a third piece of prose
 * could only restate one of them — the first drafts of these guides all did,
 * nearly verbatim. What none of them gives a newcomer is what to *do*, in
 * order, which is the one job left here.
 *
 * The copy lives here rather than in the four HTML files for the same reason
 * the tab styling lives in style.css: four copies of one thing is how the four
 * copies drift. A page opts in by giving its container a `data-guide` key;
 * test_guide.py fails if a key here has no page or a page has no key.
 *
 * No innerHTML anywhere. `*emphasis*` and `` `code` `` in the copy below are
 * expanded into real elements by segments().
 */
"use strict";

(() => {
  const GUIDES = {
    workspace: [
      "Pick a *scenario* and a *question* — the answer appears in the middle.",
      "Read the *verdict*, then the *audit trail* on the right: the facts the " +
        "decision used, and the rules that fired.",
      "Click any fact to jump to the sentence it was read from. Change the " +
        "*effective date* and watch the answer move.",
    ],
    studio: [
      "Pick a *pack* on the left — its rules render as a decision table.",
      "Edit a cell or a priority, or edit `pack.yaml` directly. Drafts live in " +
        "this demo process only; nothing is ever written to `rulepacks/`.",
      "Run *Verify* on the right: the pack's declared cases, one case by hand, " +
        "and the whole golden corpus re-adjudicated against your draft.",
    ],
    evidence: [
      "Pick a *case*, then a document or a fact from the index on the left.",
      "Highlights in the rendition are where each fact was read from — click " +
        "one to open its record in the *fact inspector*.",
      "Drag the *knowledge dial* back: facts the case had not learned yet read " +
        "*not yet known*, and the ones a later correction replaced are live again.",
    ],
    viewer: [
      "*Search* the 351 committed receipts by case id or hash, or paste one you were given.",
      "Read it as an *audit report*, or as the raw *receipt JSON* it actually is.",
      "*Verification* on the right ran when the receipt opened, not on request: " +
        "its own hash, its facts' hashes, and a full re-adjudication. A receipt " +
        "without its facts can pass only the first — *partly verified* means " +
        "the rest had nothing to check, not that something failed.",
    ],
  };

  const STORE_PREFIX = "duly.guide.v1.";

  /* Private-mode Safari throws on localStorage access rather than returning
   * null, and a guide that cannot remember being dismissed is a far smaller
   * problem than a page that fails to load. */
  function dismissed(key) {
    try {
      return window.localStorage.getItem(STORE_PREFIX + key) === "1";
    } catch {
      return false;
    }
  }

  function remember(key, value) {
    try {
      if (value) window.localStorage.setItem(STORE_PREFIX + key, "1");
      else window.localStorage.removeItem(STORE_PREFIX + key);
    } catch {
      /* the strip still opens and closes for this page view */
    }
  }

  /* `*emphasis*` -> <strong>, `` `code` `` -> <code>, everything else text. */
  function segments(copy) {
    const nodes = [];
    const pattern = /\*([^*]+)\*|`([^`]+)`/g;
    let cursor = 0;
    let match;
    while ((match = pattern.exec(copy)) !== null) {
      if (match.index > cursor) {
        nodes.push(document.createTextNode(copy.slice(cursor, match.index)));
      }
      const element = document.createElement(match[1] ? "strong" : "code");
      element.textContent = match[1] || match[2];
      nodes.push(element);
      cursor = pattern.lastIndex;
    }
    if (cursor < copy.length) nodes.push(document.createTextNode(copy.slice(cursor)));
    return nodes;
  }

  function build(guide, onDismiss) {
    const steps = document.createElement("ol");
    steps.className = "guide-steps";
    for (const copy of guide) {
      const item = document.createElement("li");
      item.append(...segments(copy));
      steps.append(item);
    }

    const dismiss = document.createElement("button");
    dismiss.className = "guide-dismiss";
    dismiss.type = "button";
    dismiss.textContent = "Got it";
    dismiss.addEventListener("click", onDismiss);

    const fragment = document.createDocumentFragment();
    fragment.append(steps, dismiss);
    return { fragment, dismiss };
  }

  function init() {
    const strip = document.getElementById("guide");
    if (!strip) return;
    const key = strip.dataset.guide;
    const guide = GUIDES[key];
    if (!guide) return;

    const intro = document.querySelector(".workspace-intro");
    const reopen = document.createElement("button");
    reopen.className = "guide-reopen";
    reopen.type = "button";
    reopen.textContent = "Show guide";
    reopen.hidden = true;
    if (intro) intro.append(reopen);

    let dismissButton = null;

    /* Focus follows the control that replaced the one you just pressed, so the
     * strip can be opened and closed without losing your place in the page. */
    const close = (moveFocus) => {
      strip.hidden = true;
      reopen.hidden = false;
      remember(key, true);
      if (moveFocus) reopen.focus();
    };

    const open = (moveFocus) => {
      strip.hidden = false;
      reopen.hidden = true;
      remember(key, false);
      if (moveFocus && dismissButton) dismissButton.focus();
    };

    const built = build(guide, () => close(true));
    dismissButton = built.dismiss;
    strip.replaceChildren(built.fragment);
    reopen.addEventListener("click", () => open(true));

    if (dismissed(key)) close(false);
    else open(false);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
