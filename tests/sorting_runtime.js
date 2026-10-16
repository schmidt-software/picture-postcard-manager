"use strict";

const assert = require("node:assert/strict");
const { setup } = require("./i18n_runtime");

async function runTests() {
  // Saved sort state is restored and applied to list requests.
  const ui = setup();
  const { run, get, context, requests, storage } = ui;
  assert.equal(get("sort-select").value, "");
  assert.equal(get("sort-direction").hidden, true);

  context.fetch = async (url) => {
    requests.push({ url });
    return { ok: true, status: 200, json: async () => [] };
  };

  // Choosing a sort key requests a sorted first page and shows the toggle.
  get("sort-select").value = "year";
  await get("sort-select").emit("change");
  assert.ok(requests.at(-1).url.includes("sort=year"), requests.at(-1).url);
  assert.ok(requests.at(-1).url.includes("dir=asc"));
  assert.ok(requests.at(-1).url.includes("offset=0"), requests.at(-1).url);
  assert.equal(get("sort-direction").hidden, false);
  assert.equal(get("sort-direction").textContent, "Ascending");
  assert.equal(storage.get("picture-postcard-manager-sort"),
    '{"key":"year","direction":"asc"}');

  // Toggling the direction flips it, persists and resets to the first page.
  await get("sort-direction").emit("click");
  assert.ok(requests.at(-1).url.includes("dir=desc"));
  assert.ok(requests.at(-1).url.includes("offset=0"), requests.at(-1).url);
  assert.equal(get("sort-direction").textContent, "Descending");
  assert.equal(get("sort-direction").attributes["aria-pressed"], "true");

  // Sorting combines with search.
  get("search").value = "Berlin";
  await run("loadList()");
  const url = requests.at(-1).url;
  assert.ok(url.includes("q=Berlin") && url.includes("sort=year") && url.includes("dir=desc"), url);

  // The direction label is localized.
  run('applyLanguage("de")');
  assert.equal(get("sort-direction").textContent, "Absteigend");
  run('applyLanguage("en")');

  // Back to default order: no sort parameters, toggle hidden.
  get("sort-select").value = "";
  await get("sort-select").emit("change");
  assert.ok(!requests.at(-1).url.includes("sort="), requests.at(-1).url);
  assert.equal(get("sort-direction").hidden, true);

  // A saved sort is restored on startup; invalid saved values fall back.
  const restored = setup();
  restored.storage.set("picture-postcard-manager-sort", '{"key":"updated","direction":"desc"}');
  restored.run("loadSavedSort(); renderSortControls();");
  assert.equal(restored.get("sort-select").value, "updated");
  assert.equal(restored.get("sort-direction").hidden, false);
  assert.equal(restored.get("sort-direction").textContent, "Descending");

  // A sort key saved before place/region were removed falls back to default.
  for (const key of ["evil", "place", "region"]) {
    const invalid = setup();
    invalid.storage.set("picture-postcard-manager-sort",
      `{"key":"${key}","direction":"desc"}`);
    invalid.run("loadSavedSort(); renderSortControls();");
    assert.equal(invalid.get("sort-select").value, "", key);
    assert.equal(invalid.get("sort-direction").hidden, true, key);
  }

  await raceTests();

  console.log("Sorting runtime checks passed.");
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

// Overlapping list requests resolved out of order: only the newest request
// may update the table, the load-more state and the error message.
async function raceTests() {
  const ui = setup();
  const { run, get, context } = ui;
  // The change/click handlers do not return the loadList promise, so the test
  // flushes microtasks after resolving each deferred fetch.
  const flush = () => new Promise(setImmediate);
  const pending = [];
  context.fetch = async (url) =>
    new Promise((resolve) => pending.push({ url, resolve }));
  const page = (items) => ({ ok: true, status: 200, json: async () => items });

  // A slow response for an old sort must not overwrite a newer one.
  get("sort-select").value = "year";
  await get("sort-select").emit("change");
  get("sort-select").value = "updated";
  await get("sort-select").emit("change");
  assert.equal(pending.length, 2);
  assert.ok(pending[0].url.includes("sort=year"), pending[0].url);
  assert.ok(pending[1].url.includes("sort=updated"), pending[1].url);
  pending[1].resolve(page([makeItem(2, "1920")])); // newest finishes first
  await flush();
  pending[0].resolve(page([makeItem(1, "1910")])); // stale finishes last
  await flush();
  assert.deepEqual(rowIds(ui), [2], "stale sort response must be dropped");

  // An append for the old sort must not extend the new sort's list.
  const pageSize = run("PAGE_SIZE");
  const fullPage = Array.from({ length: pageSize }, (_, i) => makeItem(1000 - i, "1900"));
  const refresh = run("loadList()");
  pending.at(-1).resolve(page(fullPage));
  await refresh;
  assert.equal(get("load-more").hidden, false);
  // The load-more listener returns the loadList promise; keep it pending here.
  const staleAppend = get("load-more").emit("click");
  await flush();
  assert.ok(pending.at(-1).url.includes(`offset=${pageSize}`), pending.at(-1).url);
  get("sort-select").value = "year";
  await get("sort-select").emit("change");
  pending.at(-1).resolve(page([makeItem(3, "1930")])); // new sort, first page
  await flush();
  pending.at(-2).resolve(page([makeItem(4, "1940")])); // stale append arrives late
  await staleAppend;
  assert.deepEqual(rowIds(ui), [3], "stale append must not be concatenated");
  assert.equal(get("load-more").hidden, true);

  // A stale request's failure must not raise an error over fresh results.
  get("message").hidden = true;
  const failing = run("loadList()");
  const fresh = run("loadList()");
  pending.at(-1).resolve(page([makeItem(5, "1950")]));
  await fresh;
  pending.at(-2).resolve({ ok: false, status: 500, json: async () => ({ error: "boom" }) });
  await failing;
  assert.deepEqual(rowIds(ui), [5]);
  assert.equal(get("message").hidden, true, "stale error must not be shown");
}

runTests().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
