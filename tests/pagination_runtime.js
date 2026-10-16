"use strict";

const assert = require("node:assert/strict");
const { setup } = require("./i18n_runtime");

function makeItems(start, count) {
  return Array.from({ length: count }, (_, index) => ({
    id: start - index,
    uuid: "b962a358-8899-4000-8999-6973bac5d599",
    front_image_path: "", back_image_path: "", year: "",
    tags: [], updated_at: "2026-10-04",
  }));
}

async function runTests() {
  const ui = setup();
  const { run, get, context, requests } = ui;
  const pageSize = run("PAGE_SIZE");
  assert.ok(Number.isInteger(pageSize) && pageSize > 0);

  // A full first page keeps the load-more button visible.
  const total = pageSize + 3;
  context.fetch = async (url) => {
    requests.push({ url });
    const params = new URLSearchParams(url.split("?")[1]);
    const limit = Number(params.get("limit"));
    const offset = Number(params.get("offset"));
    const count = Math.max(0, Math.min(limit, total - offset));
    return { ok: true, status: 200, json: async () => makeItems(total - offset, count) };
  };
  await run("loadList()");
  assert.equal(get("postcard-list").children.length, pageSize);
  assert.equal(get("load-more").hidden, false);
  assert.equal(get("empty-hint").hidden, true);
  const first = requests.at(-1).url;
  assert.ok(first.includes(`limit=${pageSize}`) && first.includes("offset=0"), first);

  // Loading more appends the remaining rows and hides the button.
  await get("load-more").emit("click");
  assert.equal(get("postcard-list").children.length, total);
  assert.equal(get("load-more").hidden, true);
  assert.ok(requests.at(-1).url.includes(`offset=${pageSize}`), requests.at(-1).url);

  // A new search resets to the first page.
  await run("loadList()");
  assert.equal(get("postcard-list").children.length, pageSize);
  assert.ok(requests.at(-1).url.includes("offset=0"));

  // Search terms are forwarded with pagination.
  get("search").value = "Berlin platz";
  await run("loadList()");
  assert.ok(requests.at(-1).url.includes("q=Berlin%20platz"), requests.at(-1).url);

  // An empty collection shows the hint and no button.
  get("search").value = "";
  context.fetch = async () => ({ ok: true, status: 200, json: async () => [] });
  await run("loadList()");
  assert.equal(get("postcard-list").children.length, 0);
  assert.equal(get("empty-hint").hidden, false);
  assert.equal(get("load-more").hidden, true);

  console.log("Pagination runtime checks passed.");
}

runTests().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
