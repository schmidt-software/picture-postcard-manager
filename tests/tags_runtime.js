"use strict";

const assert = require("node:assert/strict");
const { setup } = require("./i18n_runtime.js");

async function runTests() {
  const ui = setup();
  const { run, get, postcardForm, context } = ui;
  const input = get("tag-input");
  const list = get("tag-list");
  const texts = () => list.children.map((li) => li.children[0].textContent);
  const labels = () => list.children.map((li) => li.children[1].attributes["aria-label"]);
  const add = async (value) => {
    input.value = value;
    await get("add-tag").emit("click");
  };
  await new Promise(setImmediate);

  await run("openForm()");
  assert.deepEqual(texts(), []);

  await add("  Berlin, Mitte  ");
  await add("Ünïcode ✉");
  await add("Berlin, Mitte");
  await add("   ");
  input.value = "Enter <b>tag</b>";
  await input.emit("keydown", { key: "Enter" });
  assert.deepEqual(texts(), ["Berlin, Mitte", "Ünïcode ✉", "Enter <b>tag</b>"]);
  assert.equal(input.value, "");
  assert.deepEqual(labels()[0], "Remove tag Berlin, Mitte");

  run('applyLanguage("de")');
  assert.equal(labels()[1], "Schlagwort Ünïcode ✉ entfernen");
  assert.equal(get("add-tag").textContent, "Schlagwort hinzufügen");
  assert.equal(input.attributes["aria-label"], "Neues Schlagwort");

  await list.children[1].children[1].emit("click");
  assert.deepEqual(texts(), ["Berlin, Mitte", "Enter <b>tag</b>"]);

  postcardForm.elements.front_image_path.value = "/front.jpg";
  const requests = [];
  context.fetch = async (url, options) => {
    requests.push({ url, options });
    return { ok: true, status: 200, json: async () => [] };
  };
  input.value = "pending";
  await postcardForm.emit("submit");
  const post = requests.find((r) => r.options?.method === "POST");
  assert.deepEqual(JSON.parse(post.options.body).tags,
    ["Berlin, Mitte", "Enter <b>tag</b>", "pending"]);

  // Editing a postcard loads its tags; removing all of them sends an explicit [].
  await run(`openForm({ id: 5, front_image_path: "/f.jpg", tags: ["a", "b"] })`);
  assert.deepEqual(texts(), ["a", "b"]);
  for (let i = 0; i < 2; i++) await list.children[0].children[1].emit("click");
  assert.deepEqual(texts(), []);
  requests.length = 0;
  await postcardForm.emit("submit");
  const put = requests.find((r) => r.options?.method === "PUT");
  assert.deepEqual(JSON.parse(put.options.body).tags, []);

  await run("openForm()");
  assert.deepEqual(texts(), []);

  // Browse shows tags as text only.
  context.fetch = async () => ({
    ok: true, status: 200,
    json: async () => [{ id: 1, tags: ["x, y", "<img src=x>"], updated_at: "u" }],
  });
  await run("loadList()");
  const cell = get("postcard-list").children[0].children.at(-2);
  assert.deepEqual(cell.children[0].children.map((li) => li.textContent), ["x, y", "<img src=x>"]);
  console.log("Tag runtime checks passed.");
}

runTests().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
