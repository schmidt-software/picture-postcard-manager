"use strict";

// Runtime checks for the editable year combobox (issue #65): free-form entry,
// suggestion matching and ordering, keyboard/pointer/touch interaction, ARIA
// state, live region, refresh after data changes, regression of the
// four-digit-only rule, and failure handling.

const assert = require("node:assert/strict");
const { setup } = require("./i18n_runtime.js");

function makeUi(years) {
  const state = { years: [...years], failFilters: false, pending: null, saved: [] };
  const ui = setup(null, false, {
    fetch: async (url, opts = {}) => {
      if (url === "/api/postcards/filters") {
        if (state.pending) return state.pending;
        if (state.failFilters) throw new Error("network down");
        return { ok: true, status: 200, json: async () => ({ year: [...state.years], tag: [] }) };
      }
      if (url === "/api/postcards" && opts.method === "POST") {
        state.saved.push(JSON.parse(opts.body));
        return { ok: true, status: 200, json: async () => ({ id: 1 }) };
      }
      if (url.startsWith("/api/import")) {
        return { ok: true, status: 200, json: async () => ({ imported: 1 }) };
      }
      return { ok: true, status: 200, json: async () => [] };
    },
  });
  return { ui, state };
}

async function runTests() {
  const known = ["1927", "ca. 1960", "around 1800", "unknown", "1910-1920"];
  const { ui, state } = makeUi(known);
  const { run, get, timers, runTimers } = ui;
  const input = get("year-input");
  const list = get("year-suggestions");
  const status = get("year-status");
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

  await run("loadFilterOptions()");
  await flush();
  await run("openForm()");

  // Correct initial ARIA state (closed, combobox semantics).
  assert.equal(list.hidden, true);
  assert.equal(input.attributes.role, "combobox");
  assert.equal(input.attributes["aria-expanded"], "false");
  assert.equal(input.attributes["aria-controls"], "year-suggestions");
  assert.equal(input.attributes["aria-autocomplete"], "list");
  assert.equal(list.attributes.role, "listbox");

  // Focusing the empty input offers every known value in deterministic
  // locale-aware order; no request per keystroke.
  const before = ui.requests.length;
  await input.emit("focus");
  assert.equal(ui.requests.length, before, "focus must not fetch");
  assert.equal(list.hidden, false);
  assert.equal(input.attributes["aria-expanded"], "true");
  assert.deepEqual(options(), ["1910-1920", "1927", "around 1800", "ca. 1960", "unknown"]);
  assert.equal(list.children[0].attributes.role, "option");
  assert.equal(status.textContent, "5 year suggestions available.");
  assert.equal(status.attributes["aria-live"], "polite");

  // Typing narrows to case-insensitive prefix matches.
  await type("19");
  assert.deepEqual(options(), ["1910-1920", "1927"]);
  await type("CA");
  assert.deepEqual(options(), ["ca. 1960"]);
  assert.equal(status.textContent, "1 year suggestion available.");

  // No match hides the list and clears the live region; free entry works.
  await type("1850");
  assert.equal(list.hidden, true);
  assert.equal(status.textContent, "");

  // Arrow navigation with wrapping and ARIA active option.
  await type("1");
  assert.deepEqual(options(), ["1910-1920", "1927"]);
  await key("ArrowDown");
  assert.equal(input.attributes["aria-activedescendant"], "year-option-0");
  assert.equal(list.children[0].attributes["aria-selected"], "true");
  assert.equal(list.children[0].className, "tag-option active");
  await key("ArrowUp");
  assert.equal(input.attributes["aria-activedescendant"], "year-option-1", "ArrowUp must wrap");

  // Enter accepts the active suggestion, fills the field verbatim, keeps
  // focus and announces; it must not submit the form.
  await key("Enter");
  assert.equal(prevented, true, "accepting Enter must not submit");
  assert.equal(input.value, "1927");
  assert.equal(input.focused, true);
  assert.equal(list.hidden, true);
  assert.equal(status.textContent, "Year 1927 selected.");

  // Enter without an active suggestion keeps normal submit behavior (the
  // list closes, the key is not swallowed).
  await type("192");
  assert.equal(list.hidden, false);
  await key("Enter");
  assert.equal(prevented, false, "plain Enter must keep normal form behavior");
  assert.equal(list.hidden, true);
  assert.equal(input.value, "192");

  // Escape closes the list without changing the value; a second Escape is
  // not swallowed.
  await type("19");
  assert.equal(list.hidden, false);
  await key("Escape");
  assert.equal(prevented, true);
  assert.equal(list.hidden, true);
  assert.equal(input.value, "19");
  await key("Escape");
  assert.equal(prevented, false);

  // Click accepts a suggestion.
  await type("un");
  assert.deepEqual(options(), ["unknown"]);
  await list.children[0].emit("click");
  assert.equal(input.value, "unknown");
  assert.equal(input.focused, true);
  assert.equal(list.hidden, true);

  // Touch path: blur after a press defers the close; the tap's click still
  // accepts exactly once and cancels the timer.
  await type("ar");
  assert.deepEqual(options(), ["around 1800"]);
  await list.children[0].emit("pointerdown", { preventDefault() {} });
  await input.emit("blur");
  assert.equal(list.hidden, false, "press-caused blur must not close the list yet");
  assert.equal(timers.size, 1);
  await list.children[0].emit("click");
  assert.equal(input.value, "around 1800");
  assert.equal(list.hidden, true);
  assert.equal(timers.size, 0, "accepting must cancel the deferred close timer");

  // Orphaned press: the deferred close fires, fully closes, never accepts.
  await input.emit("focus");
  await type("ca");
  await list.children[0].emit("pointerdown", { preventDefault() {} });
  await input.emit("blur");
  runTimers();
  assert.equal(list.hidden, true);
  assert.equal(input.attributes["aria-expanded"], "false");
  assert.equal("aria-activedescendant" in input.attributes, false);
  assert.equal(input.value, "ca", "an orphaned press must not change the value");

  // An ordinary blur (no press) closes immediately without a timer.
  await input.emit("focus");
  await type("19");
  assert.equal(list.hidden, false);
  await input.emit("blur");
  assert.equal(list.hidden, true);
  assert.equal(timers.size, 0);

  // IME composition keys never accept prematurely.
  await input.emit("focus");
  await type("1");
  await key("ArrowDown");
  await input.emit("compositionstart");
  await key("Enter");
  assert.equal(prevented, false, "Enter during composition must pass through");
  await input.emit("compositionend");

  // Regression of the four-digit rule: free-form values save verbatim.
  await run("openForm()");
  for (const year of ["around 1800", "ca. 1960", "unknown", "1927", ""]) {
    state.saved.length = 0;
    get("postcard-form").elements.front_image_path.value = "/front.jpg";
    get("postcard-form").elements.year.value = year;
    await get("postcard-form").emit("submit");
    await flush();
    assert.equal(state.saved.length, 1, `saving year ${JSON.stringify(year)} must POST`);
    assert.equal(state.saved[0].year, year, "the exact spelling must be saved");
    assert.equal(get("message").textContent, run('translate("saved")'));
    await run("openForm()");
  }

  // Duplicate suggestion values are rendered once.
  state.years = ["1927", "1927", "ca. 1960"];
  await run("loadFilterOptions()");
  await flush();
  await input.emit("focus");
  await type("1927");
  assert.deepEqual(options(), ["1927"], "duplicates must collapse to one option");

  // Refresh: a reload of the filter values (after save/delete/import)
  // updates the open list in place while the typed text stays untouched.
  await type("1");
  assert.deepEqual(options(), ["1927"]);
  state.years = ["1888", "1927"];
  await run("loadFilterOptions()");
  await flush();
  assert.deepEqual(options(), ["1888", "1927"]);
  assert.equal(input.value, "1");

  // A stale filter-values response must not overwrite newer values.
  let resolveStale;
  state.pending = new Promise((resolve) => { resolveStale = resolve; });
  const stale = run("loadFilterOptions()");
  state.pending = null;
  state.years = ["1777"];
  await run("loadFilterOptions()");
  await flush();
  resolveStale({ ok: true, status: 200, json: async () => ({ year: ["bogus"], tag: [] }) });
  await stale;
  await flush();
  await type("1");
  assert.deepEqual(options(), ["1777"], "stale response must not overwrite suggestions");

  // A failing load degrades cleanly: previous suggestions kept, free entry works.
  state.failFilters = true;
  await run("loadFilterOptions()");
  await flush();
  await type("1");
  assert.deepEqual(options(), ["1777"]);
  await type("brand new value");
  assert.equal(list.hidden, true);

  // A language switch localizes the live region and list label.
  state.failFilters = false;
  state.years = ["1900"];
  await run("loadFilterOptions()");
  await flush();
  run('applyLanguage("de")');
  assert.equal(list.attributes["aria-label"], "Jahr-Vorschläge");
  await type("19");
  assert.equal(status.textContent, "1 Jahr-Vorschlag verfügbar.");
  await key("ArrowDown");
  await key("Enter");
  assert.equal(status.textContent, "Jahr 1900 übernommen.");
  run('applyLanguage("en")');

  // Navigating away closes the popup and cancels pending timers.
  await input.emit("focus");
  await type("19");
  assert.equal(list.hidden, false);
  await run('navigate("browse")');
  await flush();
  assert.equal(list.hidden, true);
  assert.equal(input.attributes["aria-expanded"], "false");

  console.log("Year combobox runtime checks passed.");
}

runTests().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
