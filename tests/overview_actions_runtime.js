"use strict";

const assert = require("node:assert/strict");
const { setup } = require("./i18n_runtime");

async function runTests() {
  const { run, get, context, postcardForm } = setup();
  const first = { id: 1, uuid: "b962a358-8899-4000-8999-6973bac5d599", front_image_path: "/a.png" };
  const second = { id: 2, uuid: "950b28a0-e835-4200-b801-40cc04237882", front_image_path: "/b.png" };
  let items = [first, second];
  let failDeletion = false;
  const requests = [];
  context.fetch = async (url, options = {}) => {
    requests.push({ url, options });
    if (options.method === "DELETE") {
      if (failDeletion) {
        return { ok: false, status: 404, json: async () => ({ error: "postcard not found" }) };
      }
      items = items.filter((p) => url !== `/api/postcards/${p.id}`);
      return { ok: true, status: 204 };
    }
    return {
      ok: true, status: 200,
      json: async () => url.includes("by-uuid") ? second : items,
    };
  };
  await run("loadList()");
  const row = get("postcard-list").children[1];
  const [edit, remove] = row.children.at(-1).children[0].children;
  assert.equal(edit.type, "button");
  assert.equal(remove.type, "button");
  assert.equal(edit.attributes["aria-label"], "Edit postcard #2");
  assert.equal(remove.title, "Delete postcard #2");
  assert.equal(edit.children[0].attributes["aria-hidden"], "true");
  let stopped = false;
  await edit.emit("click", { stopPropagation() { stopped = true; } });
  assert.equal(stopped, true);
  assert.equal(postcardForm.elements.id.value, 2);
  assert.equal(get("view-edit").hidden, false);
  assert.ok(!requests.some((request) => request.url.includes("by-uuid")));
  const hash = context.window.location.hash;
  for (const key of ["Enter", " "]) {
    await row.emit("keydown", { key, target: edit });
    assert.equal(context.window.location.hash, hash);
  }

  const originalQuery = context.document.querySelectorAll;
  context.document.querySelectorAll = (selector) =>
    selector === "[data-row-action]" ? [edit, remove] : originalQuery(selector);
  run('applyLanguage("de")');
  assert.equal(edit.title, "Postkarte #2 bearbeiten");
  assert.equal(remove.attributes["aria-label"], "Postkarte #2 löschen");

  const dialog = get("confirmation");
  let pending = remove.emit("click");
  assert.equal(get("confirmation-text").textContent, "Diese Postkarte löschen?");
  await remove.emit("click"); // A second activation cannot create a second dialog.
  dialog.returnValue = "cancel";
  await dialog.emit("close");
  await pending;
  assert.equal(items.length, 2);
  assert.ok(!requests.some((request) => request.options.method === "DELETE"));

  failDeletion = true;
  pending = remove.emit("click");
  dialog.returnValue = "confirm";
  await dialog.emit("close");
  await pending;
  assert.equal(items.length, 2);
  assert.equal(get("postcard-list").children.length, 2);
  assert.equal(get("message").textContent, "Fehler: Postkarte nicht gefunden.");

  failDeletion = false;
  pending = remove.emit("click");
  dialog.returnValue = "confirm";
  await dialog.emit("close");
  await pending;
  assert.deepEqual(items, [first]);
  assert.equal(get("postcard-list").children.length, 1);
  assert.equal(get("message").textContent, "Postkarte gelöscht.");
  assert.ok(requests.filter((request) => request.options.method === "DELETE")
    .every((request) => request.url === "/api/postcards/2"));

  // Non-action activation still opens the detail page.
  await row.emit("keydown", { key: "Enter" });
  await new Promise(setImmediate);
  assert.equal(context.window.location.hash, `#postcards/${second.uuid}`);
  assert.ok(requests.some((request) => request.url === `/api/postcards/by-uuid/${second.uuid}`));
  console.log("Overview action runtime checks passed.");
}

runTests().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
