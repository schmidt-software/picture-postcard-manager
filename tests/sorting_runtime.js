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
  restored.storage.set("picture-postcard-manager-sort", '{"key":"place","direction":"desc"}');
  restored.run("loadSavedSort(); renderSortControls();");
  assert.equal(restored.get("sort-select").value, "place");
  assert.equal(restored.get("sort-direction").hidden, false);
  assert.equal(restored.get("sort-direction").textContent, "Descending");

  const invalid = setup();
  invalid.storage.set("picture-postcard-manager-sort", '{"key":"evil","direction":"desc"}');
  invalid.run("loadSavedSort(); renderSortControls();");
  assert.equal(invalid.get("sort-select").value, "");
  assert.equal(invalid.get("sort-direction").hidden, true);


  console.log("Sorting runtime checks passed.");
}

runTests().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
