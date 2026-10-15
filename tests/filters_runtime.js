"use strict";

const assert = require("node:assert/strict");
const { setup } = require("./i18n_runtime");

const values = {
  place: ["Berlin, Mitte", "Munich"],
  region: ["Bavaria"],
  year: ["1910", "1920"],
  tag: ["alte Ansicht", "street"],
};

async function runTests() {
  const ui = setup();
  const { run, get, context, requests } = ui;
  context.fetch = async (url) => {
    requests.push({ url });
    return {
      ok: true, status: 200,
      json: async () => (url === "/api/postcards/filters" ? values : []),
    };
  };

  // Opening the overview loads the available filter values into the dropdowns.
  await run('showView("browse")');
  await new Promise(setImmediate);
  assert.equal(get("filter-place").children.length, 3); // All + 2 values
  assert.equal(get("filter-place").children[0].textContent, "All");
  assert.equal(get("filter-tag").children[2].textContent, "street");
  assert.equal(get("filter-reset").hidden, true);

  // Selecting a filter requests a filtered list and shows the reset button.
  requests.length = 0;
  get("filter-place").value = "Berlin, Mitte";
  await get("filter-place").emit("change");
  assert.ok(requests.at(-1).url.includes("place=Berlin%2C%20Mitte"), requests.at(-1).url);
  assert.equal(get("filter-reset").hidden, false);

  // Filters combine with each other and with search.
  get("filter-tag").value = "alte Ansicht";
  await get("filter-tag").emit("change");
  get("search").value = "color";
  await run("loadList()");
  const url = requests.at(-1).url;
  assert.ok(url.includes("q=color") && url.includes("place=") && url.includes("tag=alte%20Ansicht"), url);

  // The selection is persisted and restored.
  const saved = JSON.parse(ui.storage.get("picture-postcard-manager-filters"));
  assert.equal(saved.place, "Berlin, Mitte");
  assert.equal(saved.tag, "alte Ansicht");

  // Reset clears every filter, hides the button and reloads.
  await get("filter-reset").emit("click");
  assert.equal(get("filter-reset").hidden, true);
  assert.ok(!requests.at(-1).url.includes("place="), requests.at(-1).url);
  assert.equal(JSON.parse(ui.storage.get("picture-postcard-manager-filters")).place, "");

  // Localized labels: "All" follows the language.
  run('applyLanguage("de")');
  assert.equal(get("filter-place").children[0].textContent, "Alle");
  run('applyLanguage("en")');

  // A restored filter value missing from the options is kept selectable.
  const restored = setup();
  restored.storage.set("picture-postcard-manager-filters",
    '{"place":"Ghost town","region":"","year":"","tag":""}');
  restored.run("loadSavedFilters(); renderFilterOptions();");
  assert.equal(restored.get("filter-place").value, "Ghost town");
  assert.equal(restored.get("filter-reset").hidden, false);

  // Invalid stored values fall back to no filters.
  const invalid = setup();
  invalid.storage.set("picture-postcard-manager-filters", "not json");
  invalid.run("loadSavedFilters(); renderFilterOptions();");
  assert.equal(invalid.get("filter-place").value, "");
  assert.equal(invalid.get("filter-reset").hidden, true);

  await combinationTests();
  await raceTests();
  await runRaceTests();
  await refreshTests();

  console.log("Filter runtime checks passed.");
}

function makeItem(id, place) {
  return {
    id, uuid: "b962a358-8899-4000-8999-6973bac5d599",
    front_image_path: "", back_image_path: "", place, year: "",
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

  get("sort-select").value = "year";
  await get("sort-select").emit("change");
  get("filter-place").value = "Berlin";
  await get("filter-place").emit("change");
  get("search").value = "color";
  await run("loadList()");
  let url = requests.at(-1).url;
  assert.ok(url.includes("q=color") && url.includes("place=Berlin")
    && url.includes("sort=year") && url.includes("dir=asc")
    && url.includes("offset=0"), url);

  // Changing a filter keeps the sort and resets to the first page.
  const pageSize = run("PAGE_SIZE");
  context.fetch = async (u) => {
    requests.push({ url: u });
    return {
      ok: true, status: 200,
      json: async () => Array.from({ length: pageSize }, (_, i) => makeItem(i + 1, "A")),
    };
  };
  await run("loadList()");
  await get("load-more").emit("click");
  assert.ok(requests.at(-1).url.includes(`offset=${pageSize}`), requests.at(-1).url);
  assert.ok(requests.at(-1).url.includes("sort=year")
    && requests.at(-1).url.includes("place=Berlin"), requests.at(-1).url);
  get("filter-year").value = "1910";
  await get("filter-year").emit("change");
  url = requests.at(-1).url;
  assert.ok(url.includes("offset=0") && url.includes("sort=year")
    && url.includes("place=Berlin") && url.includes("year=1910"), url);

  // Reset clears the filters but keeps the sort and returns to page one.
  await get("filter-reset").emit("click");
  url = requests.at(-1).url;
  assert.ok(!url.includes("place=") && url.includes("sort=year")
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
  get("sort-select").value = "place";
  await get("sort-select").emit("change");
  get("filter-place").value = "Berlin";
  await get("filter-place").emit("change");
  assert.equal(pending.length, 2);
  assert.ok(pending[0].url.includes("sort=place"), pending[0].url);
  assert.ok(pending[1].url.includes("sort=place")
    && pending[1].url.includes("place=Berlin"), pending[1].url);
  pending[1].resolve(page([makeItem(2, "Berlin")])); // newest finishes first
  await flush();
  pending[0].resolve(page([makeItem(1, "Augsburg")])); // stale finishes last
  await flush();
  assert.deepEqual(rowIds(ui), [2], "stale filtered+sorted response must be dropped");

  // A stale failure while a filter and a sort are active must stay silent.
  get("message").hidden = true;
  const failing = run("loadList()");
  const fresh = run("loadList()");
  pending.at(-1).resolve(page([makeItem(3, "Berlin")]));
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
    front_image_path: "", back_image_path: "", place: "", year: "",
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
  run('currentFilters.place = "Old town"');
  const oldLoad = run("loadList()");
  run('currentFilters.place = "New town"');
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
  run('currentFilters.place = "Other town"');
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
  run('currentFilters = { place: "", region: "", year: "", tag: "" }');
  const oldOptions = run("loadFilterOptions()");
  const newOptions = run("loadFilterOptions()");
  pending[1].resolve({ place: ["Current"], region: [], year: [], tag: [] });
  await newOptions;
  pending[0].resolve({ place: ["Stale A", "Stale B"], region: [], year: [], tag: [] });
  await oldOptions;
  const options = get("filter-place").children.map((option) => option.textContent);
  assert.deepEqual(options.slice(1), ["Current"], "stale response rebuilt the dropdowns");
}

// Every change to the collection must refresh the filter dropdowns, not only
// the list: a value whose last postcard disappears is removed as an option.
async function refreshTests() {
  const ui = setup();
  const { run, get, context, requests, postcardForm, importForm } = ui;
  const flush = () => new Promise(setImmediate);
  const uuid = "b962a358-8899-4000-8999-6973bac5d599";
  let options = { place: ["Berlin", "Munich"], region: [], year: [], tag: [] };
  context.fetch = async (url, opts = {}) => {
    requests.push({ url, options: opts });
    if (opts.method === "DELETE") {
      options = { ...options, place: options.place.filter((p) => p !== "Berlin") };
      return { ok: true, status: 204 };
    }
    if (opts.method === "POST" && url.startsWith("/api/import")) {
      options = { ...options, place: [...options.place, "Imported"] };
      return { ok: true, status: 200, json: async () => ({ imported: 1 }) };
    }
    if (opts.method === "POST") {
      options = { ...options, place: [...options.place, "Vienna"] };
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
  const placeOptions = () =>
    get("filter-place").children.map((option) => option.textContent).slice(1);
  const dialog = get("confirmation");
  const confirmPending = async (pending) => {
    dialog.returnValue = "confirm";
    await dialog.emit("close");
    await pending;
    await flush();
  };

  await run('showView("browse")');
  await flush();
  assert.deepEqual(placeOptions(), ["Berlin", "Munich"]);

  // Deleting directly in the overview reloads the dropdowns: the deleted
  // postcard may have carried the last use of a value.
  requests.length = 0;
  await confirmPending(run("deletePostcard(1)"));
  assert.ok(requests.some((request) => request.url === "/api/postcards/filters"),
    "deleting in the overview must reload the filter options");
  assert.deepEqual(placeOptions(), ["Munich"], "deleted value must leave the dropdown");

  // A selected value whose last postcard is deleted stays selectable with an
  // empty result (same rule as a restored value) instead of breaking the select.
  options = { ...options, place: ["Berlin", "Munich"] };
  await run('showView("browse")');
  await flush();
  get("filter-place").value = "Berlin";
  await get("filter-place").emit("change");
  await confirmPending(run("deletePostcard(1)"));
  assert.equal(get("filter-place").value, "Berlin", "selection must survive the refresh");
  assert.deepEqual(placeOptions(), ["Berlin", "Munich"]);
  assert.equal(get("filter-reset").hidden, false);
  assert.ok(requests.at(-1).url.includes("place=Berlin"), requests.at(-1).url);
  await get("filter-reset").emit("click");

  // Deleting from the edit form returns to the overview, which reloads the
  // dropdowns on entry.
  context.window.location.hash = `#postcards/${uuid}/edit`;
  await run("route()");
  await flush();
  assert.equal(get("view-edit").hidden, false);
  requests.length = 0;
  await confirmPending(run("deletePostcard(2)"));
  assert.ok(requests.some((request) => request.url === "/api/postcards/filters"),
    "deleting from the edit form must reload the filter options");
  assert.deepEqual(placeOptions(), ["Munich"]);

  // Saving returns to the overview, which reloads the dropdowns on entry.
  options = { ...options, place: ["Munich"] };
  await run('openForm()');
  postcardForm.elements.front_image_path.value = "/f.jpg";
  requests.length = 0;
  await postcardForm.emit("submit");
  await flush();
  assert.ok(requests.some((request) => request.url === "/api/postcards/filters"),
    "saving must reload the filter options");
  assert.deepEqual(placeOptions(), ["Munich", "Vienna"], "saved value must appear");

  // After an import, returning to the overview reloads the dropdowns.
  await run('navigate("data")');
  importForm.elements.file.files = [{ name: "import.json", text: async () => "[]" }];
  await importForm.emit("submit");
  await flush();
  requests.length = 0;
  await run('navigate("browse")');
  await flush();
  assert.ok(requests.some((request) => request.url === "/api/postcards/filters"),
    "returning to the overview after an import must reload the filter options");
  assert.ok(placeOptions().includes("Imported"), "imported value must appear");
}

runTests().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
