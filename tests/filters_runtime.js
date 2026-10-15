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

runTests().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
