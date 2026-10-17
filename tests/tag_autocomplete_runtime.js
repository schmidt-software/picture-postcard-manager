"use strict";

// Runtime checks for the tag-input autocomplete (issue #47): matching,
// ordering, keyboard/pointer interaction, ARIA state, live region, refresh
// events, failure handling and stale-response safety.

const assert = require("node:assert/strict");
const { setup } = require("./i18n_runtime.js");

function makeUi(tags) {
  const state = { tags: [...tags], failFilters: false, failImport: false, pending: null };
  const ui = setup(null, false, {
    fetch: async (url, opts) => {
      if (url === "/api/postcards/filters") {
        if (state.pending) return state.pending;
        if (state.failFilters) throw new Error("network down");
        return { ok: true, status: 200, json: async () => ({ year: [], tag: [...state.tags] }) };
      }
      if (url.startsWith("/api/import")) {
        if (state.failImport) {
          return { ok: false, status: 400, json: async () => ({ error: "unsupported import format" }) };
        }
        return { ok: true, status: 200, json: async () => ({ imported: 1 }) };
      }
      return { ok: true, status: 200, json: async () => [] };
    },
  });
  return { ui, state };
}

async function runTests() {
  const known = ["Berlin", "berlin, mitte", "Bern", "Wien", "Ähren", "ähnlich", "<img src=x>"];
  const { ui, state } = makeUi(known);
  const { run, get, context } = ui;
  const input = get("tag-input");
  const list = get("tag-suggestions");
  const status = get("tag-status");
  const chips = () => get("tag-list").children.map((li) => li.children[0].textContent);
  const options = () => list.children.map((li) => li.textContent);
  const flush = () => new Promise(setImmediate);
  let prevented = false;
  const key = (name, extra = {}) => {
    prevented = false;
    return input.emit("keydown", { key: name, preventDefault: () => { prevented = true; }, ...extra });
  };
  const type = async (value) => {
    input.value = value;
    await input.emit("input");
  };
  await flush();

  // Load the suggestion source once via the shared filter-values cache.
  await run("loadFilterOptions()");
  await flush();

  await run("openForm()");
  await input.emit("focus");

  // Closed on empty input; correct initial ARIA state.
  assert.equal(list.hidden, true);
  assert.equal(input.attributes["aria-expanded"], "false");
  assert.equal(input.attributes.role, "combobox");
  assert.equal(input.attributes["aria-controls"], "tag-suggestions");
  assert.equal(list.attributes.role, "listbox");

  // Case-insensitive prefix match preserving stored spelling; exact-case
  // prefix matches first, then locale-aware alphabetical order; whitespace
  // around the typed prefix is ignored; no request per keystroke.
  const before = ui.requests.length;
  await type("  be  ");
  assert.equal(ui.requests.length, before, "typing must not fetch");
  assert.deepEqual(options(), ["berlin, mitte", "Berlin", "Bern"]);
  assert.equal(list.hidden, false);
  assert.equal(input.attributes["aria-expanded"], "true");
  assert.equal(list.children[0].attributes.role, "option");
  assert.equal(status.textContent, "3 tag suggestions available.");

  await type("Be");
  assert.deepEqual(options(), ["Berlin", "Bern", "berlin, mitte"],
    "exact-case prefix matches must come first");

  // Unicode-aware matching (case folding beyond ASCII).
  await type("ä");
  assert.deepEqual(options(), ["ähnlich", "Ähren"]);

  // Hostile tag text stays inert text (textContent, never markup).
  await type("<img");
  assert.deepEqual(options(), ["<img src=x>"]);

  // No match hides the list and clears the live region.
  await type("zzz");
  assert.equal(list.hidden, true);
  assert.equal(input.attributes["aria-expanded"], "false");
  assert.equal(status.textContent, "");
  assert.equal(status.attributes["aria-live"], "polite");

  // Tab without an open list must keep normal focus navigation.
  await key("Tab");
  assert.equal(prevented, false, "Tab must not be prevented when the list is closed");

  // Tab with an open list accepts the first suggestion, clears the input,
  // keeps focus and announces the accepted tag.
  await type("wie");
  assert.equal(status.textContent, "1 tag suggestion available.");
  await key("Tab");
  assert.equal(prevented, true, "Tab must be prevented when accepting");
  assert.deepEqual(chips(), ["Wien"]);
  assert.equal(input.value, "");
  assert.equal(input.focused, true);
  assert.equal(list.hidden, true);
  assert.equal(status.textContent, "Tag Wien added.");

  // The already-selected tag is excluded from further suggestions.
  await type("wie");
  assert.equal(list.hidden, true);

  // Arrow navigation wraps and drives aria-activedescendant/aria-selected.
  await type("be");
  await key("ArrowDown");
  assert.equal(input.attributes["aria-activedescendant"], "tag-option-0");
  assert.equal(list.children[0].attributes["aria-selected"], "true");
  assert.equal(list.children[0].className, "tag-option active");
  await key("ArrowDown");
  assert.equal(input.attributes["aria-activedescendant"], "tag-option-1");
  assert.equal(list.children[0].attributes["aria-selected"], "false");
  await key("ArrowUp");
  await key("ArrowUp");
  assert.equal(input.attributes["aria-activedescendant"], "tag-option-2", "ArrowUp must wrap");

  // Enter accepts the active suggestion.
  await key("Enter");
  assert.equal(prevented, true);
  assert.deepEqual(chips(), ["Wien", "Bern"]);
  assert.equal(input.value, "");

  // Enter without an active suggestion keeps the existing add-typed-tag
  // behavior, even while suggestions are visible.
  await type("ber");
  assert.deepEqual(options(), ["berlin, mitte", "Berlin"]);
  await key("Enter");
  assert.deepEqual(chips(), ["Wien", "Bern", "ber"], "typed text must be added as-is");
  assert.equal(list.hidden, true);

  // Escape closes the list without changing the input; a second Escape is
  // not swallowed (no preventDefault when the list is already closed).
  await type("be");
  assert.equal(list.hidden, false);
  await key("Escape");
  assert.equal(prevented, true);
  assert.equal(list.hidden, true);
  assert.equal(input.value, "be");
  await key("Escape");
  assert.equal(prevented, false);

  // Click accepts a suggestion.
  await type("Äh");
  assert.deepEqual(options(), ["Ähren", "ähnlich"]);
  await list.children[0].emit("click");
  assert.deepEqual(chips(), ["Wien", "Bern", "ber", "Ähren"]);
  assert.equal(input.value, "");

  // Removing a chip makes its tag suggestible again for the current prefix.
  await type("wie");
  assert.equal(list.hidden, true);
  await get("tag-list").children[0].children[1].emit("click");
  assert.deepEqual(options(), ["Wien"]);

  // Blur closes the list; refocusing with text restores it.
  await input.emit("blur");
  assert.equal(list.hidden, true);
  await input.emit("focus");
  assert.deepEqual(options(), ["Wien"]);

  // IME composition keys must not accept or commit prematurely.
  await input.emit("compositionstart");
  await key("Enter");
  assert.equal(prevented, false, "Enter during composition must pass through");
  await key("Tab");
  assert.equal(prevented, false, "Tab during composition must pass through");
  await input.emit("compositionend");
  assert.deepEqual(options(), ["Wien"]);
  await key("Enter", { isComposing: true });
  assert.equal(prevented, false, "isComposing events must pass through");

  // Form reset (openForm) clears input, chips and suggestions.
  await run("openForm()");
  assert.deepEqual(chips(), []);
  assert.equal(input.value, "");
  assert.equal(list.hidden, true);
  assert.equal(input.attributes["aria-expanded"], "false");

  // Editing a postcard: its selected tags filter the suggestions.
  await run(`openForm({ id: 3, front_image_path: "/f.jpg", tags: ["Berlin"] })`);
  await input.emit("focus");
  await type("be");
  assert.deepEqual(options(), ["berlin, mitte", "Bern"]);

  // A language switch re-sorts with the new locale and keeps the active
  // option by value; the localized texts apply from now on.
  await key("ArrowDown");
  await key("ArrowDown");
  assert.equal(options()[1], "Bern");
  run('applyLanguage("de")');
  assert.deepEqual(options(), ["berlin, mitte", "Bern"]);
  assert.equal(list.children[1].attributes["aria-selected"], "true",
    "active option must survive a language switch");
  await key("Enter");
  assert.equal(status.textContent, "Schlagwort Bern hinzugefügt.");
  assert.equal(list.attributes["aria-label"], "Schlagwort-Vorschläge");
  await type("be");
  assert.equal(status.textContent, "1 Schlagwort-Vorschlag verfügbar.");
  run('applyLanguage("en")');

  // Refresh: a reload of the filter values (after save/delete/import) updates
  // the open list in place — new tags appear, removed tags disappear — while
  // the typed text stays untouched.
  state.tags = ["Bergen", "Wien"];
  await run("loadFilterOptions()");
  await flush();
  assert.deepEqual(options(), ["Bergen"]);
  assert.equal(input.value, "be");

  // A stale filter-values response must not overwrite newer values.
  let resolveStale;
  state.pending = new Promise((resolve) => { resolveStale = resolve; });
  const stale = run("loadFilterOptions()");
  state.pending = null;
  state.tags = ["Beta", "Wien"];
  await run("loadFilterOptions()");
  await flush();
  resolveStale({ ok: true, status: 200, json: async () => ({ year: [], tag: ["Bogus"] }) });
  await stale;
  await flush();
  assert.deepEqual(options(), ["Beta"], "stale response must not overwrite suggestions");

  // A failing filter-values load degrades cleanly: the previous suggestions
  // are kept and free tag entry still works.
  state.failFilters = true;
  await run("loadFilterOptions()");
  await flush();
  assert.deepEqual(options(), ["Beta"]);
  await type("Brand new tag");
  assert.equal(list.hidden, true);
  await key("Enter");
  assert.ok(chips().includes("Brand new tag"), "free tag entry must keep working");

  // A failure before any successful load leaves the list hidden entirely.
  const freshUi = makeUi([]);
  freshUi.state.failFilters = true;
  const fresh = freshUi.ui;
  await new Promise(setImmediate);
  await fresh.run("loadFilterOptions()");
  await new Promise(setImmediate);
  await fresh.run("openForm()");
  const freshInput = fresh.get("tag-input");
  await freshInput.emit("focus");
  freshInput.value = "anything";
  await freshInput.emit("input");
  assert.equal(fresh.get("tag-suggestions").hidden, true);
  freshInput.value = "still works";
  await freshInput.emit("keydown", { key: "Enter", preventDefault() {} });
  assert.deepEqual(fresh.get("tag-list").children.map((li) => li.children[0].textContent),
    ["still works"]);

  await pointerSelectionTests();
  await unicodeNormalizationTests();
  await importRefreshTests();

  console.log("Tag autocomplete runtime checks passed.");
}

// Touch-first browsers may blur the input on an option press despite the
// pointerdown preventDefault; the following click must still accept the
// option exactly once, keep focus in the input, and an ordinary outside blur
// must keep closing the list. Every non-accept terminal path (deferred close
// timer, pointercancel, pointerleave, Escape/reset while pending) must
// resolve the pending press so the list never stays logically open. The
// harness provides deterministic fake timers (ui.timers/ui.runTimers).
async function pointerSelectionTests() {
  const { ui, state } = makeUi(["Paris", "Prag"]);
  const { run, get, timers, runTimers } = ui;
  const input = get("tag-input");
  const list = get("tag-suggestions");
  const chips = () => get("tag-list").children.map((li) => li.children[0].textContent);
  const flush = () => new Promise(setImmediate);
  await flush();
  await run("loadFilterOptions()");
  await flush();
  await run("openForm()");
  await input.emit("focus");
  input.value = "pa";
  await input.emit("input");
  assert.equal(list.hidden, false);

  // (5) Desktop/mousedown-fallback path: pointerdown + mousedown both fire
  // and prevent default; the input never blurs; one click accepts exactly
  // once (the press handlers never accept themselves).
  let prevented = 0;
  const press = { preventDefault: () => { prevented += 1; } };
  await list.children[0].emit("pointerdown", press);
  await list.children[0].emit("mousedown", press);
  assert.equal(prevented, 2, "both press events must prevent the focus steal");
  await list.children[0].emit("click");
  assert.deepEqual(chips(), ["Paris"], "click after press must accept exactly once");
  assert.equal(input.focused, true);
  assert.equal(list.hidden, true);
  assert.equal(timers.size, 0, "a focused accept must not leave a close timer");

  // (2) Touch path: the browser blurs the input between pointerdown and the
  // tap's click. The deferred close keeps the option alive; the click before
  // the timer fires accepts exactly once, refocuses and cancels the timer.
  await input.emit("focus");
  input.value = "pr";
  await input.emit("input");
  assert.equal(list.hidden, false);
  await list.children[0].emit("pointerdown", { preventDefault() {} });
  await input.emit("blur");
  assert.equal(list.hidden, false, "press-caused blur must not close the list yet");
  assert.equal(timers.size, 1, "a press-caused blur must schedule the deferred close");
  await list.children[0].emit("click");
  assert.deepEqual(chips(), ["Paris", "Prag"], "tap must accept exactly once");
  assert.equal(input.focused, true, "accepting must refocus the input");
  assert.equal(list.hidden, true);
  assert.equal(timers.size, 0, "accepting must cancel the deferred close timer");
  runTimers(); // No stray timer may mutate anything after the accept.
  assert.deepEqual(chips(), ["Paris", "Prag"]);

  // (1) Orphaned press: pointerdown -> blur with neither click nor cancel.
  // The deferred close fires and fully closes the list (hidden,
  // aria-expanded=false, no aria-activedescendant), with no acceptance.
  state.tags = ["Paris", "Prag", "Pavia"];
  await run("loadFilterOptions()");
  await flush();
  await input.emit("focus");
  input.value = "pav";
  await input.emit("input");
  await input.emit("keydown", { key: "ArrowDown", preventDefault() {} });
  assert.equal(input.attributes["aria-activedescendant"], "tag-option-0");
  await list.children[0].emit("pointerdown", { preventDefault() {} });
  await input.emit("blur");
  assert.equal(list.hidden, false, "the list survives until the deferred close");
  runTimers();
  assert.equal(list.hidden, true, "an orphaned press must eventually close the list");
  assert.equal(input.attributes["aria-expanded"], "false");
  assert.equal("aria-activedescendant" in input.attributes, false,
    "closing must clear aria-activedescendant");
  assert.deepEqual(chips(), ["Paris", "Prag"], "an orphaned press must not accept");
  assert.equal(timers.size, 0);
  // The pending state is fully resolved: a later outside blur closes
  // immediately again (no deferral from stale pending state).
  await input.emit("focus");
  input.value = "pav";
  await input.emit("input");
  assert.equal(list.hidden, false);
  await input.emit("blur");
  assert.equal(list.hidden, true, "pending state must not leak into later blurs");
  assert.equal(timers.size, 0);

  // (3) A cancelled press (pointercancel) after a blur closes immediately
  // and never accepts; the deferred timer is cleaned up.
  await input.emit("focus");
  input.value = "pav";
  await input.emit("input");
  const option = list.children[0];
  await option.emit("pointerdown", { preventDefault() {} });
  await input.emit("blur");
  await option.emit("pointercancel");
  assert.equal(list.hidden, true, "cancelled press after blur must close the list");
  assert.deepEqual(chips(), ["Paris", "Prag"], "a cancelled press must not accept");
  assert.equal(timers.size, 0, "pointercancel must clear the deferred close timer");

  // (3) pointerleave (pointer dragged off the option before release) is an
  // equivalent abandon path.
  await input.emit("focus");
  input.value = "pav";
  await input.emit("input");
  const leaveOption = list.children[0];
  await leaveOption.emit("pointerdown", { preventDefault() {} });
  await input.emit("blur");
  await leaveOption.emit("pointerleave");
  assert.equal(list.hidden, true, "pointerleave after blur must close the list");
  assert.deepEqual(chips(), ["Paris", "Prag"], "pointerleave must not accept");
  assert.equal(timers.size, 0);
  // While the input stays focused, pointerleave only abandons the press and
  // keeps the list open for keyboard use.
  await input.emit("focus");
  input.value = "pav";
  await input.emit("input");
  await list.children[0].emit("pointerdown", { preventDefault() {} });
  await list.children[0].emit("pointerleave");
  assert.equal(list.hidden, false, "a focused abandoned press keeps the list open");

  // (4) Escape while a press is pending (after blur) closes at once, cancels
  // the timer, and the later timer run must not reopen or mutate anything.
  await list.children[0].emit("pointerdown", { preventDefault() {} });
  await input.emit("blur");
  assert.equal(timers.size, 1);
  await input.emit("focus"); // focus returns (e.g. Escape routing refocuses)
  assert.equal(timers.size, 0, "refocusing must cancel the deferred close");
  await input.emit("keydown", { key: "Escape", preventDefault() {} });
  assert.equal(list.hidden, true);
  runTimers();
  assert.equal(list.hidden, true, "no stale timer may reopen the list");

  // (4) Form reset (openForm) while a press is pending: closeSuggestions
  // clears pending state and timer; the timer run must not touch the new form.
  await input.emit("focus");
  input.value = "pav";
  await input.emit("input");
  await list.children[0].emit("pointerdown", { preventDefault() {} });
  await input.emit("blur");
  assert.equal(timers.size, 1);
  await run("openForm()");
  assert.equal(list.hidden, true);
  assert.equal(timers.size, 0, "reset must clear the pending close timer");
  runTimers();
  assert.equal(list.hidden, true, "no timer may mutate the reset form");
  assert.deepEqual(chips(), [], "the new form must stay empty");

  // An ordinary outside blur (no pending press) still closes the list
  // immediately, without scheduling a timer.
  await input.emit("focus");
  input.value = "pa";
  await input.emit("input");
  assert.equal(list.hidden, false);
  await input.emit("blur");
  assert.equal(list.hidden, true, "outside blur must close the list");
  assert.equal(timers.size, 0, "outside blur must not schedule a timer");
}

// Composed/decomposed Unicode must match in both directions (NFC before the
// locale case fold); the fold is toLocaleLowerCase, not full Unicode case
// folding (so "ss" never matches "ß"). Stored spellings are preserved and
// NFC-equivalent duplicates with different code sequences stay distinct
// stored tags with deterministic order.
async function unicodeNormalizationTests() {
  const composed = "Caf\u00e9"; // Café (U+00E9)
  const decomposed = "Cafe\u0301 au lait"; // e + combining acute
  const known = [composed, decomposed, "Stra\u00dfe", "STRA\u1e9eE", "\u0130stanbul", "Istanbul", "izmir"];
  const { ui } = makeUi(known);
  const { run, get } = ui;
  const input = get("tag-input");
  const list = get("tag-suggestions");
  const options = () => list.children.map((li) => li.textContent);
  const type = async (value) => {
    input.value = value;
    await input.emit("input");
  };
  await new Promise(setImmediate);
  await run("loadFilterOptions()");
  await new Promise(setImmediate);
  await run("openForm()");
  await input.emit("focus");

  // Composed prefix matches both stored forms; spellings stay as stored.
  await type("caf\u00e9");
  assert.deepEqual(options(), [composed, decomposed]);
  // Decomposed prefix matches both directions too.
  await type("cafe\u0301");
  assert.deepEqual(options(), [composed, decomposed]);

  // German sharp s: the capital ẞ folds to ß, so ß prefixes match both...
  await type("stra\u00df");
  assert.deepEqual(options(), ["Stra\u00dfe", "STRA\u1e9eE"]);
  // ...but "ss" does not (locale lowercase fold, not full Unicode casefold).
  await type("strass");
  assert.equal(list.hidden, true);

  // Under the shipped EN and DE locales a plain "i" matches I, İ and i
  // (İ lowercases to i + combining dot); Turkish dotless-I rules would only
  // apply under a "tr" locale, which the UI does not ship.
  for (const language of ["en", "de"]) {
    run(`applyLanguage(${JSON.stringify(language)})`);
    await type("i");
    assert.deepEqual(options(), ["izmir", "Istanbul", "\u0130stanbul"],
      `locale ${language}: I/\u0130/i must all match a plain i prefix`);
  }
}

// A successful JSON import refreshes the shared filter-values cache exactly
// once, so the autocomplete knows newly imported tags immediately — even when
// the form is opened without revisiting the overview. A failed import leaves
// the cache untouched.
async function importRefreshTests() {
  const { ui, state } = makeUi(["Old"]);
  const { run, get, importForm, requests } = ui;
  const input = get("tag-input");
  const list = get("tag-suggestions");
  const options = () => list.children.map((li) => li.textContent);
  const flush = () => new Promise(setImmediate);
  const filterRequests = () =>
    requests.filter((request) => request.url === "/api/postcards/filters").length;
  await flush();
  await run("loadFilterOptions()");
  await flush();

  // Success: exactly one shared refresh, no duplicate requests.
  state.tags = ["Old", "Imported City"];
  importForm.elements.file.files = [{ name: "import.json", text: async () => "{}" }];
  requests.length = 0;
  await importForm.emit("submit");
  await flush();
  assert.equal(filterRequests(), 1,
    "a successful import must refresh the filter values exactly once");
  assert.equal(get("message").textContent, run('translate("imported", { count: 1 })'),
    "the import success message must be preserved");

  // The new tag is suggestible immediately, without visiting the overview.
  await run("openForm()");
  await input.emit("focus");
  input.value = "imp";
  await input.emit("input");
  assert.deepEqual(options(), ["Imported City"],
    "imported tags must be available to the autocomplete immediately");

  // Failure: no refresh, cache and suggestions unchanged, error shown.
  state.failImport = true;
  state.tags = ["Old", "Imported City", "Never Loaded"];
  importForm.elements.file.files = [{ name: "bad.json", text: async () => "{}" }];
  requests.length = 0;
  await importForm.emit("submit");
  await flush();
  assert.equal(filterRequests(), 0, "a failed import must not refresh the filter values");
  input.value = "nev";
  await input.emit("input");
  assert.equal(list.hidden, true, "a failed import must not overwrite the cached tags");
  input.value = "imp";
  await input.emit("input");
  assert.deepEqual(options(), ["Imported City"], "the previous cache must survive a failed import");
}

runTests().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
