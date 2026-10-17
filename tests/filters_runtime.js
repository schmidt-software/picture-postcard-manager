"use strict";

const assert = require("node:assert/strict");
const { setup } = require("./i18n_runtime");

const values = {
  year: ["1910", "1920"],
  tag: ["alte Ansicht", "Berlin, Mitte", "street"],
};

function chipTexts(ui) {
  return ui.get("filter-tag-list").children.map((li) => li.children[0].textContent);
}

function tagChoices(ui) {
  return ui.get("filter-tag").children.map((option) => option.textContent).slice(1);
}

async function selectTag(ui, tag) {
  ui.get("filter-tag").value = tag;
  await ui.get("filter-tag").emit("change");
}

function urlTags(ui) {
  return new URLSearchParams(
    new URL(ui.context.window.location.href).search).getAll("tag");
}

async function runTests() {
  const ui = setup();
  const { run, get, context, requests } = ui;
  const flush = () => new Promise(setImmediate);
  context.fetch = async (url) => {
    requests.push({ url });
    return {
      ok: true, status: 200,
      json: async () => (url === "/api/postcards/filters" ? values : []),
    };
  };

  // Opening the overview loads the available filter values into the controls.
  await run('showView("browse")');
  await flush();
  assert.equal(get("filter-year").children.length, 3); // All + 2 values
  assert.equal(get("filter-year").children[0].textContent, "All");
  // The tag add-select offers all known tags after a placeholder, in a
  // deterministic locale-aware order with the stored spelling.
  assert.deepEqual(tagChoices(ui), ["alte Ansicht", "Berlin, Mitte", "street"]);
  assert.equal(get("filter-reset").hidden, true);
  assert.equal(get("filter-tag-clear").hidden, true);
  // The removed place/region filter dropdowns no longer exist.
  assert.equal(get("filter-place"), undefined);
  assert.equal(get("filter-region"), undefined);

  // Selecting a tag adds a chip, requests a filtered list, shows reset and
  // clear-all, removes the chosen tag from the choices and announces it.
  requests.length = 0;
  await selectTag(ui, "Berlin, Mitte");
  assert.ok(requests.at(-1).url.includes("tag=Berlin%2C+Mitte")
    || requests.at(-1).url.includes("tag=Berlin%2C%20Mitte"), requests.at(-1).url);
  assert.deepEqual(chipTexts(ui), ["Berlin, Mitte"]);
  assert.deepEqual(tagChoices(ui), ["alte Ansicht", "street"]);
  assert.equal(get("filter-reset").hidden, false);
  assert.equal(get("filter-tag-clear").hidden, false);
  assert.equal(get("filter-tag-status").textContent, "Tag filter Berlin, Mitte added.");
  assert.equal(get("filter-tag").focused, true, "focus stays on the add-select");
  // The select returns to the placeholder so another tag can be added.
  assert.equal(get("filter-tag").value, "");
  // The chip's remove button carries a localized accessible name.
  const chip = get("filter-tag-list").children[0];
  assert.equal(chip.children[1].attributes["aria-label"],
    "Remove tag filter Berlin, Mitte");
  // The selection is mirrored into the URL as a repeated tag parameter.
  assert.deepEqual(urlTags(ui), ["Berlin, Mitte"]);

  // Adding a second tag keeps the first; the request repeats the parameter in
  // selection order (AND semantics on the server).
  await selectTag(ui, "street");
  assert.deepEqual(chipTexts(ui), ["Berlin, Mitte", "street"]);
  let url = requests.at(-1).url;
  const tagParams = new URLSearchParams(url.split("?")[1]).getAll("tag");
  assert.deepEqual(tagParams, ["Berlin, Mitte", "street"]);
  assert.deepEqual(urlTags(ui), ["Berlin, Mitte", "street"]);

  // Filters combine with each other and with search.
  get("filter-year").value = "1910";
  await get("filter-year").emit("change");
  get("search").value = "color";
  await run("loadList()");
  url = requests.at(-1).url;
  assert.ok(url.includes("q=color") && url.includes("year=1910"), url);
  assert.deepEqual(new URLSearchParams(url.split("?")[1]).getAll("tag"),
    ["Berlin, Mitte", "street"]);

  // The selection is persisted (as an array) and restored.
  const saved = JSON.parse(ui.storage.get("picture-postcard-manager-filters"));
  assert.deepEqual(saved.tag, ["Berlin, Mitte", "street"]);
  assert.equal(saved.year, "1910");

  // Removing one chip keeps the others, moves focus to the next chip and
  // updates URL and request.
  requests.length = 0;
  await get("filter-tag-list").children[0].children[1].emit("click");
  assert.deepEqual(chipTexts(ui), ["street"]);
  assert.deepEqual(urlTags(ui), ["street"]);
  assert.equal(get("filter-tag-status").textContent, "Tag filter Berlin, Mitte removed.");
  assert.equal(get("filter-tag-list").children[0].children[1].focused, true,
    "focus moves to the chip at the removed position");
  assert.deepEqual(new URLSearchParams(requests.at(-1).url.split("?")[1]).getAll("tag"),
    ["street"]);

  // Removing the last chip moves focus to the add-select.
  get("filter-tag").focused = false;
  await get("filter-tag-list").children[0].children[1].emit("click");
  assert.deepEqual(chipTexts(ui), []);
  assert.deepEqual(urlTags(ui), []);
  assert.equal(get("filter-tag").focused, true);
  assert.equal(get("filter-tag-clear").hidden, true);

  // Clear-all removes every selected tag at once.
  await selectTag(ui, "street");
  await selectTag(ui, "alte Ansicht");
  assert.deepEqual(chipTexts(ui), ["street", "alte Ansicht"]);
  await get("filter-tag-clear").emit("click");
  assert.deepEqual(chipTexts(ui), []);
  assert.deepEqual(urlTags(ui), []);
  assert.equal(get("filter-tag-status").textContent, "All tag filters removed.");

  // Reset clears every filter, hides the button, clears the URL and reloads.
  await selectTag(ui, "street");
  await get("filter-reset").emit("click");
  assert.equal(get("filter-reset").hidden, true);
  assert.deepEqual(chipTexts(ui), []);
  assert.deepEqual(urlTags(ui), []);
  assert.ok(!requests.at(-1).url.includes("tag="), requests.at(-1).url);
  assert.deepEqual(
    JSON.parse(ui.storage.get("picture-postcard-manager-filters")).tag, []);

  // Localized labels: "All", the add placeholder and the fieldset legend
  // follow the language; announcements are localized too.
  run('applyLanguage("de")');
  assert.equal(get("filter-year").children[0].textContent, "Alle");
  assert.equal(get("filter-tag").children[0].textContent, "Schlagwort hinzufügen…");
  await selectTag(ui, "street");
  assert.equal(get("filter-tag-status").textContent,
    "Schlagwort-Filter street hinzugefügt.");
  assert.equal(get("filter-tag-list").children[0].children[1].attributes["aria-label"],
    "Schlagwort-Filter street entfernen");
  await get("filter-reset").emit("click");
  run('applyLanguage("en")');

  // A restored selection with tags missing from the options is kept as
  // removable chips (stale tags stay selected, never silently dropped).
  const restored = setup();
  restored.storage.set("picture-postcard-manager-filters",
    '{"year":"","tag":["Ghost town","street"]}');
  restored.run("loadSavedFilters(); renderFilterOptions();");
  assert.deepEqual(chipTexts(restored), ["Ghost town", "street"]);
  assert.equal(restored.get("filter-reset").hidden, false);

  // Legacy single-tag storage (a string, pre issue #52) migrates to a
  // one-element selection; an empty string means no tags.
  const legacySingle = setup();
  legacySingle.storage.set("picture-postcard-manager-filters",
    '{"year":"1910","tag":"Old town"}');
  legacySingle.run("loadSavedFilters(); renderFilterOptions();");
  assert.deepEqual(chipTexts(legacySingle), ["Old town"]);
  assert.equal(legacySingle.get("filter-year").value, "1910");
  const legacyEmpty = setup();
  legacyEmpty.storage.set("picture-postcard-manager-filters",
    '{"year":"","tag":""}');
  legacyEmpty.run("loadSavedFilters(); renderFilterOptions();");
  assert.deepEqual(chipTexts(legacyEmpty), []);
  assert.equal(legacyEmpty.get("filter-reset").hidden, true);
  // A legacy whitespace-only saved string is dropped like a blank one.
  const legacyBlank = setup();
  legacyBlank.storage.set("picture-postcard-manager-filters",
    '{"year":"","tag":"   "}');
  legacyBlank.run("loadSavedFilters(); renderFilterOptions();");
  assert.deepEqual(chipTexts(legacyBlank), []);
  assert.equal(legacyBlank.get("filter-reset").hidden, true);

  // A stored filter from before the removal of place/region is ignored for
  // the removed keys but keeps the surviving ones.
  const legacy = setup();
  legacy.storage.set("picture-postcard-manager-filters",
    '{"place":"Berlin","region":"Bavaria","year":"1910","tag":""}');
  legacy.run("loadSavedFilters(); renderFilterOptions();");
  assert.equal(legacy.get("filter-year").value, "1910");
  assert.equal(JSON.stringify(legacy.run("FILTER_KEYS")), '["year","tag"]');

  // Invalid stored values fall back to no filters; stored arrays are
  // canonicalized (blanks, whitespace-only values and non-strings dropped,
  // duplicates removed).
  const invalid = setup();
  invalid.storage.set("picture-postcard-manager-filters", "not json");
  invalid.run("loadSavedFilters(); renderFilterOptions();");
  assert.equal(invalid.get("filter-year").value, "");
  assert.equal(invalid.get("filter-reset").hidden, true);
  const dirty = setup();
  dirty.storage.set("picture-postcard-manager-filters",
    '{"year":"","tag":["A","A",""," ","\\t",5,"B"]}');
  dirty.run("loadSavedFilters(); renderFilterOptions();");
  assert.deepEqual(chipTexts(dirty), ["A", "B"]);

  await urlTests();
  await combinationTests();
  await raceTests();
  await runRaceTests();
  await refreshTests();

  console.log("Filter runtime checks passed.");
}

// URL round trip: the URL is authoritative on entering the overview. Its
// repeated tag parameters are parsed, canonicalized (duplicates, blanks and
// whitespace-only values dropped) and applied over any stored selection; a
// URL without tag parameters means no tag filter. Hostile and Unicode
// values pass through URLSearchParams escaping unchanged.
async function urlTests() {
  const hostile = "<script>&=?#%\"'";
  const unicode = "Wien Café 😀";
  const shared = setup(null, false, {
    url: "http://127.0.0.1:8000/?tag=street&tag=" +
      encodeURIComponent(hostile) + "&tag=street&tag=&tag=%20%20&tag=" +
      encodeURIComponent(unicode),
  });
  shared.storage.set("picture-postcard-manager-filters",
    '{"year":"","tag":["Stored tag"]}');
  shared.context.fetch = async (url) => {
    shared.requests.push({ url });
    return { ok: true, status: 200, json: async () => [] };
  };
  shared.run("loadSavedFilters(); renderFilterOptions();");
  await shared.run("route()");
  await new Promise(setImmediate);
  // URL wins over storage; duplicates, blanks and whitespace-only values are
  // dropped, order kept.
  assert.deepEqual(chipTexts(shared), ["street", hostile, unicode]);
  // The canonical URL contains each value exactly once, properly escaped.
  assert.deepEqual(urlTags(shared), ["street", hostile, unicode]);
  const canonical = new URL(shared.context.window.location.href);
  assert.ok(!canonical.search.includes("<script>"),
    "special characters must be escaped in the URL");
  // The list request repeats the (escaped) tag parameters; no blank value is
  // ever forwarded to the backend.
  const listUrl = shared.requests.find((r) => r.url.startsWith("/api/postcards?"));
  assert.deepEqual(new URLSearchParams(listUrl.url.split("?")[1]).getAll("tag"),
    ["street", hostile, unicode]);
  // The canonicalized selection is persisted.
  assert.deepEqual(
    JSON.parse(shared.storage.get("picture-postcard-manager-filters")).tag,
    ["street", hostile, unicode]);

  // A bare URL (no tag parameters) is authoritative too: previously active
  // and stored tags are cleared and the cleared state is persisted, so a
  // direct or shared link without tags reliably means no tag filter.
  const bare = setup();
  bare.storage.set("picture-postcard-manager-filters",
    '{"year":"","tag":["Stored tag"]}');
  bare.context.fetch = async (url) => {
    bare.requests.push({ url });
    return { ok: true, status: 200, json: async () => [] };
  };
  bare.run("loadSavedFilters(); renderFilterOptions();");
  assert.deepEqual(chipTexts(bare), ["Stored tag"]);
  await bare.run("route()");
  await new Promise(setImmediate);
  assert.deepEqual(chipTexts(bare), [], "bare URL must clear active tags");
  assert.deepEqual(urlTags(bare), [], "cleared tags must not be re-injected");
  assert.deepEqual(
    JSON.parse(bare.storage.get("picture-postcard-manager-filters")).tag, [],
    "the cleared selection must be persisted");
  const bareList = bare.requests.find((r) => r.url.startsWith("/api/postcards?"));
  assert.ok(!new URLSearchParams(bareList.url.split("?")[1]).has("tag"),
    bareList.url);

  // A URL whose tag parameters are all blank/whitespace-only behaves like a
  // bare URL: zero chips, zero stored tags, zero URL parameters, and no
  // blank value reaches the backend (which would answer HTTP 400).
  const blankOnly = setup(null, false, {
    url: "http://127.0.0.1:8000/?tag=&tag=%20&tag=%09",
  });
  blankOnly.context.fetch = async (url) => {
    blankOnly.requests.push({ url });
    return { ok: true, status: 200, json: async () => [] };
  };
  await blankOnly.run("route()");
  await new Promise(setImmediate);
  assert.deepEqual(chipTexts(blankOnly), []);
  assert.deepEqual(urlTags(blankOnly), []);
  // Nothing changed relative to the empty default, so nothing needs to be
  // persisted; stored state, if any, must not contain tags.
  const storedBlank = blankOnly.storage.get("picture-postcard-manager-filters");
  assert.deepEqual(storedBlank === undefined ? [] : JSON.parse(storedBlank).tag, []);
  const blankList = blankOnly.requests.find((r) => r.url.startsWith("/api/postcards?"));
  assert.ok(!new URLSearchParams(blankList.url.split("?")[1]).has("tag"),
    blankList.url);

  // Back/Forward: entering the overview again re-reads the tag parameters of
  // the restored URL, so history navigation restores the selection.
  const nav = setup(null, false, { url: "http://127.0.0.1:8000/?tag=One" });
  nav.context.fetch = async (url) => {
    nav.requests.push({ url });
    return { ok: true, status: 200, json: async () => [] };
  };
  await nav.run("route()");
  await new Promise(setImmediate);
  assert.deepEqual(chipTexts(nav), ["One"]);
  // Navigate to the data view and back: the selection survives.
  await nav.run('navigate("data")');
  await nav.run('navigate("browse")');
  await new Promise(setImmediate);
  assert.deepEqual(chipTexts(nav), ["One"]);
  assert.deepEqual(urlTags(nav), ["One"]);
  // Simulate Back to the data view and Forward to the overview.
  await nav.context.window.history.go(-1);
  await nav.context.window.history.go(1);
  await new Promise(setImmediate);
  assert.deepEqual(chipTexts(nav), ["One"]);

  // Back/Forward to an overview URL without tag parameters clears the
  // selection: the URL is authoritative in both directions. History is
  // built only through natural app operations: a bare overview entry, a
  // data-view entry, a second overview entry that then gets a tag (selection
  // changes use replaceState, so only view navigations create entries).
  const cleared = setup();
  cleared.context.fetch = async (url) => {
    cleared.requests.push({ url });
    return { ok: true, status: 200, json: async () => [] };
  };
  await cleared.run("route()"); // entry 1: bare overview
  await new Promise(setImmediate);
  await cleared.run('navigate("data")'); // entry 2: data view (bare URL)
  await cleared.run('navigate("browse")'); // entry 3: overview
  await new Promise(setImmediate);
  await selectTag(cleared, "Berlin"); // replaceState: entry 3 now carries the tag
  assert.deepEqual(urlTags(cleared), ["Berlin"]);
  await cleared.run('navigate("data")'); // entry 4: data view (tagged URL)
  // Back returns to the tagged overview entry...
  await cleared.context.window.history.go(-1);
  await new Promise(setImmediate);
  assert.deepEqual(chipTexts(cleared), ["Berlin"]);
  // ...and Back across the data entry to the original bare overview entry
  // clears the chips, the stored selection and the request parameters.
  await cleared.context.window.history.go(-1); // entry 2: data view
  await cleared.context.window.history.go(-1); // entry 1: bare overview
  await new Promise(setImmediate);
  assert.deepEqual(chipTexts(cleared), [],
    "Back to a bare overview URL must clear the selection");
  assert.deepEqual(urlTags(cleared), []);
  assert.deepEqual(
    JSON.parse(cleared.storage.get("picture-postcard-manager-filters")).tag, []);
  const lastList = [...cleared.requests].reverse()
    .find((r) => r.url.startsWith("/api/postcards?"));
  assert.ok(!new URLSearchParams(lastList.url.split("?")[1]).has("tag"),
    lastList.url);
  // Forward restores the tagged overview entry and its selection.
  await cleared.context.window.history.go(1); // entry 2: data view
  await cleared.context.window.history.go(1); // entry 3: tagged overview
  await new Promise(setImmediate);
  assert.deepEqual(chipTexts(cleared), ["Berlin"],
    "Forward to a tagged overview URL must restore the selection");
}

function makeItem(id, year) {
  return {
    id, uuid: "b962a358-8899-4000-8999-6973bac5d599",
    front_image_path: "", back_image_path: "", year,
    tags: [], updated_at: "2026-10-04",
  };
}

function rowIds(ui) {
  return ui.get("postcard-list").children.map((tr) => tr.children[0].textContent);
}

// Filters, sorting, search and pagination combine into one request; changing
// a filter or resetting returns to the first page while keeping the sort.
async function combinationTests() {
  const ui = setup();
  const { run, get, context, requests } = ui;
  context.fetch = async (url) => {
    requests.push({ url });
    return { ok: true, status: 200, json: async () => [] };
  };

  get("sort-select").value = "updated";
  await get("sort-select").emit("change");
  await selectTag(ui, "Berlin");
  get("search").value = "color";
  await run("loadList()");
  let url = requests.at(-1).url;
  assert.ok(url.includes("q=color") && url.includes("tag=Berlin")
    && url.includes("sort=updated") && url.includes("dir=asc")
    && url.includes("offset=0"), url);

  // Changing a filter keeps the sort and resets to the first page.
  const pageSize = run("PAGE_SIZE");
  context.fetch = async (u) => {
    requests.push({ url: u });
    return {
      ok: true, status: 200,
      json: async () => Array.from({ length: pageSize }, (_, i) => makeItem(i + 1, "1910")),
    };
  };
  await run("loadList()");
  await get("load-more").emit("click");
  assert.ok(requests.at(-1).url.includes(`offset=${pageSize}`), requests.at(-1).url);
  assert.ok(requests.at(-1).url.includes("sort=updated")
    && requests.at(-1).url.includes("tag=Berlin"), requests.at(-1).url);
  get("filter-year").value = "1910";
  await get("filter-year").emit("change");
  url = requests.at(-1).url;
  assert.ok(url.includes("offset=0") && url.includes("sort=updated")
    && url.includes("tag=Berlin") && url.includes("year=1910"), url);

  // Adding a second tag also returns to the first page, keeping everything.
  await selectTag(ui, "Night");
  url = requests.at(-1).url;
  assert.ok(url.includes("offset=0") && url.includes("sort=updated")
    && url.includes("year=1910"), url);
  assert.deepEqual(new URLSearchParams(url.split("?")[1]).getAll("tag"),
    ["Berlin", "Night"]);

  // Reset clears the filters but keeps the sort and returns to page one.
  await get("filter-reset").emit("click");
  url = requests.at(-1).url;
  assert.ok(!url.includes("tag=") && url.includes("sort=updated")
    && url.includes("offset=0"), url);
}

// Overlapping list requests resolved in reverse order while sorting AND
// filtering are both active: only the newest request may update the table,
// the load-more state and the error message.
async function raceTests() {
  const ui = setup();
  const { run, get, context } = ui;
  const flush = () => new Promise(setImmediate);
  const pending = [];
  context.fetch = async (url) =>
    new Promise((resolve) => pending.push({ url, resolve }));
  const page = (items) => ({ ok: true, status: 200, json: async () => items });

  // Sort first, then change a filter: the older sorted-and-unfiltered
  // request resolves last and must be dropped.
  get("sort-select").value = "year";
  await get("sort-select").emit("change");
  await selectTag(ui, "Berlin");
  assert.equal(pending.length, 2);
  assert.ok(pending[0].url.includes("sort=year"), pending[0].url);
  assert.ok(pending[1].url.includes("sort=year")
    && pending[1].url.includes("tag=Berlin"), pending[1].url);
  pending[1].resolve(page([makeItem(2, "1920")])); // newest finishes first
  await flush();
  pending[0].resolve(page([makeItem(1, "1910")])); // stale finishes last
  await flush();
  assert.deepEqual(rowIds(ui), [2], "stale filtered+sorted response must be dropped");

  // A stale failure while a filter and a sort are active must stay silent.
  get("message").hidden = true;
  const failing = run("loadList()");
  const fresh = run("loadList()");
  pending.at(-1).resolve(page([makeItem(3, "1930")]));
  await fresh;
  pending.at(-2).resolve({ ok: false, status: 500, json: async () => ({ error: "boom" }) });
  await failing;
  assert.deepEqual(rowIds(ui), [3]);
  assert.equal(get("message").hidden, true, "stale error must not be shown");
}

function makeItems(ids) {
  return ids.map((id) => ({
    id,
    uuid: "b962a358-8899-4000-8999-6973bac5d599",
    front_image_path: "", back_image_path: "", year: "",
    tags: [], updated_at: "2026-10-04",
  }));
}

function listedIds(ui) {
  return ui.get("postcard-list").children.map((tr) => Number(tr.children[0].textContent));
}

// Overlapping requests resolved in reverse order: only the newest request may
// update the list, the error display and the filter dropdowns. Without the
// request guards in loadList()/loadFilterOptions() every check below fails.
async function runRaceTests() {
  const ui = setup();
  const { run, get, context } = ui;
  const pending = [];
  context.fetch = async (url) => {
    const deferred = { url };
    deferred.body = new Promise((resolve) => (deferred.resolve = resolve));
    pending.push(deferred);
    return { ok: !url.includes("fail"), status: 200, json: () => deferred.body };
  };

  // A slower response for an old filter must not replace a newer filter's list.
  run('currentFilters.tag = ["Old town"]');
  const oldLoad = run("loadList()");
  run('currentFilters.tag = ["New town"]');
  const newLoad = run("loadList()");
  assert.equal(pending.length, 2);
  pending[1].resolve(makeItems([7]));
  await newLoad;
  assert.deepEqual(listedIds(ui), [7]);
  pending[0].resolve(makeItems([1, 2, 3]));
  await oldLoad;
  assert.deepEqual(listedIds(ui), [7], "stale response overwrote a newer list");

  // A stale append for an old filter must not extend the new filter's list.
  pending.length = 0;
  const staleAppend = run("loadList(true)");
  run('currentFilters.tag = ["Other town"]');
  const freshLoad = run("loadList()");
  pending[1].resolve(makeItems([9]));
  await freshLoad;
  pending[0].resolve(makeItems([4, 5]));
  await staleAppend;
  assert.deepEqual(listedIds(ui), [9], "stale append extended a newer list");

  // The load-more state follows the newest request only: a stale short page
  // must not hide the button a newer full page keeps visible.
  pending.length = 0;
  const pageSize = run("PAGE_SIZE");
  const shortLoad = run("loadList()");
  const fullLoad = run("loadList()");
  pending[1].resolve(makeItems(Array.from({ length: pageSize }, (_, i) => i + 1)));
  await fullLoad;
  assert.equal(get("load-more").hidden, false);
  pending[0].resolve(makeItems([1]));
  await shortLoad;
  assert.equal(get("load-more").hidden, false, "stale response hid the load-more button");

  // A stale failure must not raise an error for a list the user already left.
  pending.length = 0;
  get("search").value = "fail";
  const failing = run("loadList()");
  get("search").value = "";
  const succeeding = run("loadList()");
  pending[1].resolve(makeItems([8]));
  await succeeding;
  pending[0].resolve({ error: "postcard must be an object" });
  await failing;
  assert.equal(get("message").hidden, true, "stale failure displayed an error");
  assert.deepEqual(listedIds(ui), [8]);

  // Stale filter values must not overwrite dropdowns a newer request rebuilt.
  pending.length = 0;
  run('currentFilters = { year: "", tag: [] }');
  const oldOptions = run("loadFilterOptions()");
  const newOptions = run("loadFilterOptions()");
  pending[1].resolve({ year: [], tag: ["Current"] });
  await newOptions;
  pending[0].resolve({ year: [], tag: ["Stale A", "Stale B"] });
  await oldOptions;
  assert.deepEqual(tagChoices(ui), ["Current"], "stale response rebuilt the dropdowns");
}

// Every change to the collection must refresh the filter choices, not only
// the list: a value whose last postcard disappears is removed as a choice.
async function refreshTests() {
  const ui = setup();
  const { run, get, context, requests, postcardForm, importForm } = ui;
  const flush = () => new Promise(setImmediate);
  const uuid = "b962a358-8899-4000-8999-6973bac5d599";
  let options = { year: [], tag: ["Berlin", "Munich"] };
  context.fetch = async (url, opts = {}) => {
    requests.push({ url, options: opts });
    if (opts.method === "DELETE") {
      options = { ...options, tag: options.tag.filter((p) => p !== "Berlin") };
      return { ok: true, status: 204 };
    }
    if (opts.method === "POST" && url.startsWith("/api/import")) {
      options = { ...options, tag: [...options.tag, "Imported"] };
      return { ok: true, status: 200, json: async () => ({ imported: 1 }) };
    }
    if (opts.method === "POST") {
      options = { ...options, tag: [...options.tag, "Vienna"] };
      return { ok: true, status: 200, json: async () => ({ id: 9 }) };
    }
    return {
      ok: true, status: 200,
      json: async () => {
        if (url === "/api/postcards/filters") return options;
        if (url.includes("by-uuid")) return { id: 2, uuid, front_image_path: "/a.png" };
        return [];
      },
    };
  };
  const dialog = get("confirmation");
  const confirmPending = async (pending) => {
    dialog.returnValue = "confirm";
    await dialog.emit("close");
    await pending;
    await flush();
  };

  await run('showView("browse")');
  await flush();
  assert.deepEqual(tagChoices(ui), ["Berlin", "Munich"]);

  // Deleting directly in the overview reloads the choices: the deleted
  // postcard may have carried the last use of a value.
  requests.length = 0;
  await confirmPending(run("deletePostcard(1)"));
  assert.ok(requests.some((request) => request.url === "/api/postcards/filters"),
    "deleting in the overview must reload the filter options");
  assert.deepEqual(tagChoices(ui), ["Munich"], "deleted value must leave the choices");

  // A selected tag whose last postcard is deleted stays selected as a chip
  // (same rule as a restored value), showing an empty result until removed.
  options = { ...options, tag: ["Berlin", "Munich"] };
  await run('showView("browse")');
  await flush();
  await selectTag(ui, "Berlin");
  await confirmPending(run("deletePostcard(1)"));
  assert.deepEqual(chipTexts(ui), ["Berlin"], "selection must survive the refresh");
  assert.deepEqual(tagChoices(ui), ["Munich"],
    "removed value no longer appears as a choice");
  assert.equal(get("filter-reset").hidden, false);
  assert.ok(requests.at(-1).url.includes("tag=Berlin"), requests.at(-1).url);
  await get("filter-reset").emit("click");

  // Deleting from the edit form returns to the overview, which reloads the
  // choices on entry.
  context.window.location.hash = `#postcards/${uuid}/edit`;
  await run("route()");
  await flush();
  assert.equal(get("view-edit").hidden, false);
  requests.length = 0;
  await confirmPending(run("deletePostcard(2)"));
  assert.ok(requests.some((request) => request.url === "/api/postcards/filters"),
    "deleting from the edit form must reload the filter options");
  assert.deepEqual(tagChoices(ui), ["Munich"]);

  // Saving returns to the overview, which reloads the choices on entry.
  options = { ...options, tag: ["Munich"] };
  await run('openForm()');
  postcardForm.elements.front_image_path.value = "/f.jpg";
  requests.length = 0;
  await postcardForm.emit("submit");
  await flush();
  assert.ok(requests.some((request) => request.url === "/api/postcards/filters"),
    "saving must reload the filter options");
  assert.deepEqual(tagChoices(ui), ["Munich", "Vienna"], "saved value must appear");

  // After an import, returning to the overview reloads the choices.
  await run('navigate("data")');
  importForm.elements.file.files = [{ name: "import.json", text: async () => "[]" }];
  await importForm.emit("submit");
  await flush();
  requests.length = 0;
  await run('navigate("browse")');
  await flush();
  assert.ok(requests.some((request) => request.url === "/api/postcards/filters"),
    "returning to the overview after an import must reload the filter options");
  assert.ok(tagChoices(ui).includes("Imported"), "imported value must appear");
}

runTests().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
