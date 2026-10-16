"use strict";

const assert = require("node:assert/strict");
const { setup } = require("./i18n_runtime");

async function runTests() {
  const { run, get, context, postcardForm } = setup();
  const first = { id: 1, uuid: "b962a358-8899-4000-8999-6973bac5d599", front_image_path: "/a.png" };
  const second = { id: 2, uuid: "950b28a0-e835-4200-b801-40cc04237882", front_image_path: "/b.png" };
  // The server state is newer than the overview snapshot that rendered the row.
  const fresh = { ...second, description: "Changed elsewhere" };
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
      json: async () => url.includes("by-uuid") ? fresh : items,
    };
  };
  const flush = () => new Promise(setImmediate);
  // A detail page visited earlier must not decide where Cancel returns to.
  context.window.location.hash = `#postcards/${second.uuid}`;
  await run("route()");
  await get("detail-back").emit("click");
  let row = get("postcard-list").children[1];
  const [edit, removeButton] = row.children.at(-1).children[0].children;
  assert.equal(edit.type, "button");
  assert.equal(removeButton.type, "button");
  assert.equal(edit.attributes["aria-label"], "Edit postcard #2");
  assert.equal(removeButton.title, "Delete postcard #2");
  assert.equal(edit.children[0].attributes["aria-hidden"], "true");
  let stopped = false;
  await edit.emit("click", { stopPropagation() { stopped = true; } });
  assert.equal(stopped, true);
  assert.equal(context.window.location.hash, `#postcards/${second.uuid}/edit`);
  assert.equal(postcardForm.elements.id.value, 2);
  assert.equal(postcardForm.elements.description.value, "Changed elsewhere");
  assert.equal(get("view-edit").hidden, false);
  await get("cancel").emit("click");
  await flush();
  assert.equal(context.window.location.hash, "#browse");
  assert.equal(get("view-browse").hidden, false);

  row = get("postcard-list").children[1];
  const hash = context.window.location.hash;
  for (const key of ["Enter", " "]) {
    await row.emit("keydown", { key, target: row.children.at(-1).children[0].children[0] });
    assert.equal(context.window.location.hash, hash);
  }

  // A language change re-renders every row label in the new language.
  run('applyLanguage("de")');
  row = get("postcard-list").children[1];
  const remove = row.children.at(-1).children[0].children[1];
  assert.equal(row.children.at(-1).children[0].children[0].title, "Postkarte #2 bearbeiten");
  assert.equal(remove.attributes["aria-label"], "Postkarte #2 löschen");
  assert.equal(row.attributes["aria-label"], "Postkarte #2 ansehen");
  const historyLength = context.window.history.length;

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
  assert.equal(context.window.history.length, historyLength); // No duplicate #browse entries.
  assert.ok(requests.filter((request) => request.options.method === "DELETE")
    .every((request) => request.url === "/api/postcards/2"));

  // Non-action activation still opens the detail page.
  await row.emit("keydown", { key: "Enter" });
  await new Promise(setImmediate);
  assert.equal(context.window.location.hash, `#postcards/${second.uuid}`);
  assert.ok(requests.some((request) => request.url === `/api/postcards/by-uuid/${second.uuid}`));
  await navigationChecks();
  console.log("Overview action runtime checks passed.");
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((done, failed) => { resolve = done; reject = failed; });
  return { promise, resolve, reject };
}

// Review follow-up: stale responses, loading state and history after deletion.
async function navigationChecks() {
  const card = { id: 7, uuid: "b962a358-8899-4000-8999-6973bac5d599", front_image_path: "/c.png" };
  const ok = (data) => ({ ok: true, status: 200, json: async () => data });
  const flush = () => new Promise(setImmediate);
  const pending = [];
  const { run, get, context, postcardForm } = setup();
  const history = context.window.history;
  const hash = () => context.window.location.hash;
  // Before the first list response the overview must not claim to be empty.
  assert.equal(get("empty-hint").hidden, true);
  context.fetch = (url, options = {}) => {
    // Filter dropdown values load alongside the overview list; answer them
    // directly so the indexed responses below keep addressing the list,
    // detail and delete requests.
    if (url === "/api/postcards/filters") {
      return Promise.resolve(ok({ year: [], tag: [] }));
    }
    const response = deferred();
    pending.push({ url, options, response });
    return response.promise;
  };
  const respond = async (index, data) => {
    pending[index].response.resolve(data);
    await flush();
  };

  // An older list response cannot replace a newer one.
  run("loadList()");
  run("loadList()");
  await respond(1, ok([card]));
  await respond(0, ok([]));
  assert.equal(get("postcard-list").children.length, 1);
  assert.equal(get("empty-hint").hidden, true);

  // While the postcard loads, only a status is shown; New cancels the request.
  run(`navigate("postcards/${card.uuid}/edit")`);
  assert.equal(get("view-edit").hidden, false);
  assert.equal(get("edit-status").hidden, false);
  assert.equal(get("postcard-form").hidden, true);
  run('navigate("new")');
  assert.equal(get("postcard-form").hidden, false);
  await respond(2, ok(card));
  assert.equal(postcardForm.elements.id.value, "");
  assert.equal(hash(), "#new");

  // A temporary failure returns to the detail page the edit was opened from.
  run(`navigate("postcards/${card.uuid}")`);
  await respond(3, ok(card));
  get("detail-edit").emit("click");
  pending[4].response.reject(new Error("server error"));
  await flush();
  await flush();
  assert.equal(hash(), `#postcards/${card.uuid}`);
  await respond(5, ok(card));
  assert.equal(get("view-detail").hidden, false);
  assert.equal(get("detail-title").textContent, "Postcard #7");

  // Deleting from the edit form steps back over every entry of that postcard.
  run('navigate("browse")');
  await respond(6, ok([card]));
  const browseIndex = history.index;
  run(`navigate("postcards/${card.uuid}")`);
  await respond(7, ok(card));
  get("detail-edit").emit("click");
  await respond(8, ok(card));
  assert.equal(postcardForm.elements.id.value, 7);
  const deletion = get("delete").emit("click");
  get("confirmation").returnValue = "confirm";
  await get("confirmation").emit("close");
  await respond(9, { ok: true, status: 204 });
  await respond(10, ok([]));
  await deletion;
  assert.equal(history.index, browseIndex);
  assert.equal(hash(), "#browse");
  assert.equal(get("view-browse").hidden, false);

  // A deletion started in the overview must not discard a form opened meanwhile.
  run('navigate("browse")');
  await respond(11, ok([card]));
  const rowRemove = get("postcard-list").children[0].children.at(-1).children[0].children[1];
  const overviewDeletion = rowRemove.emit("click");
  get("confirmation").returnValue = "confirm";
  await get("confirmation").emit("close");
  await flush();
  assert.equal(pending[12].options.method, "DELETE");
  run('navigate("new")');
  postcardForm.elements.year.value = "Typed";
  await respond(12, { ok: true, status: 204 });
  await overviewDeletion;
  await flush();
  assert.equal(hash(), "#new");
  assert.equal(get("view-edit").hidden, false);
  assert.equal(postcardForm.elements.year.value, "Typed");

  // A failed edit load from the overview leaves no duplicate overview entry.
  run('navigate("browse")');
  await respond(13, ok([card]));
  const overviewIndex = history.index;
  run(`navigate("postcards/${card.uuid}/edit")`);
  pending[14].response.reject(new Error("server error"));
  await flush();
  await flush();
  assert.equal(history.index, overviewIndex);
  assert.equal(hash(), "#browse");

  // Without app entries to return to (opened directly), the entry is replaced.
  const direct = setup(null, false, {
    url: `http://127.0.0.1:8000/#postcards/${card.uuid}/edit`,
    fetch: async (url, options = {}) => ok(options.method === "DELETE" ? null : url.includes("by-uuid") ? card : []),
  });
  await flush();
  const directDeletion = direct.get("delete").emit("click");
  direct.get("confirmation").returnValue = "confirm";
  await direct.get("confirmation").emit("close");
  await directDeletion;
  assert.equal(direct.context.window.history.length, 1);
  assert.equal(direct.context.window.location.hash, "#browse");
}

let finished = false;
process.on("exit", (code) => {
  if (!finished && code === 0) {
    console.error("Overview action runtime checks did not finish.");
    process.exitCode = 1;
  }
});
runTests().then(() => { finished = true; }, (error) => {
  console.error(error);
  process.exitCode = 1;
});
