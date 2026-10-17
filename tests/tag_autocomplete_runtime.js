"use strict";

// Runtime checks for the tag-input autocomplete (issue #47): matching,
// ordering, keyboard/pointer interaction, ARIA state, live region, refresh
// events, failure handling and stale-response safety.

const assert = require("node:assert/strict");
const { setup } = require("./i18n_runtime.js");

function makeUi(tags) {
  const state = { tags: [...tags], failFilters: false, pending: null };
  const ui = setup(null, false, {
    fetch: async (url) => {
      if (url === "/api/postcards/filters") {
        if (state.pending) return state.pending;
        if (state.failFilters) throw new Error("network down");
        return { ok: true, status: 200, json: async () => ({ year: [], tag: [...state.tags] }) };
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

  console.log("Tag autocomplete runtime checks passed.");
}

runTests().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
