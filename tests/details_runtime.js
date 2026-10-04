"use strict";

const assert = require("node:assert/strict");
const { setup } = require("./i18n_runtime");
const firstUuid = "b962a358-8899-4000-8999-6973bac5d599";
const secondUuid = "950b28a0-e835-4200-b801-40cc04237882";

const postcard = {
  id: 42, uuid: firstUuid, front_image_path: "/images/front.png", back_image_path: "/images/back.png",
  place: "<script>Place</script>", region: "Region", year: "1905",
  description: "Line one\nLine two <b>unchanged</b>", tags: ["Tag, with comma", "Deutsch"],
};
const response = (data) => ({ ok: true, status: 200, json: async () => data });
const flush = () => new Promise(setImmediate);

async function runTests() {
  const ui = setup(null, false, {
    url: `https://postcards.example/#postcards/${firstUuid}`,
    fetch: async () => response(postcard),
  });
  const { run, get, context, postcardForm } = ui;
  await flush();
  assert.equal(ui.requests[0].url, `/api/postcards/by-uuid/${firstUuid}`);
  assert.equal(get("view-detail").hidden, false);
  assert.equal(get("view-edit").hidden, true);
  assert.equal(get("detail-title").textContent, "Postcard #42");
  assert.equal(get("detail-content").hidden, false);
  assert.equal(get("share-url").value, `https://postcards.example/#postcards/${firstUuid}`);
  assert.equal(get("detail-photos").children.length, 2);
  const front = get("detail-photos").children[0].children.at(-1);
  assert.equal(front.loading, "eager");
  assert.equal(front.src, "https://postcards.example/images/front.png");
  assert.equal(front.alt, "Front image");
  await front.emit("load");
  assert.equal(front.style.visibility, "visible");
  await front.emit("error");
  assert.equal(front.hidden, true);
  assert.equal(get("detail-photos").children[0].children[1].hidden, false);
  const metadata = get("detail-metadata").children;
  assert.equal(metadata[1].textContent, postcard.place);
  assert.equal(metadata[3].textContent, postcard.region);
  assert.equal(metadata[5].textContent, postcard.year);
  assert.equal(metadata[7].textContent, postcard.description);
  assert.deepEqual(metadata[9].children[0].children.map((chip) => chip.textContent), postcard.tags);

  run('applyLanguage("de")');
  assert.equal(get("detail-title").textContent, "Postkarte #42");
  assert.equal(get("detail-metadata").children[0].textContent, "Ort");
  assert.equal(get("detail-metadata").children[1].textContent, postcard.place);
  assert.equal(get("detail-photos").children[0].children.at(-1).alt, "Vorderseite");

  const copied = [];
  context.navigator.clipboard = { writeText: async (value) => copied.push(value) };
  await get("copy-share-link").emit("click");
  assert.deepEqual(copied, [`https://postcards.example/#postcards/${firstUuid}`]);
  assert.equal(get("share-status").textContent, "Link kopiert.");
  run('applyLanguage("en")');
  assert.equal(get("share-status").textContent, "Link copied.");
  for (const clipboard of [undefined, { writeText: async () => { throw new Error("Denied"); } }]) {
    context.navigator.clipboard = clipboard;
    await get("copy-share-link").emit("click");
    assert.equal(get("share-url").focused, true);
    assert.equal(get("share-url").selected, true);
    assert.match(get("share-status").textContent, /copy it manually/);
  }

  await get("detail-edit").emit("click");
  assert.equal(get("view-edit").hidden, false);
  assert.equal(postcardForm.elements.region.value, postcard.region);
  assert.equal(postcardForm.elements.description.value, postcard.description);
  assert.equal(context.window.location.hash, `#postcards/${firstUuid}`);
  await get("cancel").emit("click");
  assert.equal(get("view-detail").hidden, false);
  assert.equal(get("detail-title").textContent, "Postcard #42");
  context.fetch = async (url) => response(url === "/api/postcards" ? [postcard] : postcard);
  await get("detail-back").emit("click");
  await flush();
  assert.equal(context.window.location.hash, "#browse");
  assert.equal(get("view-browse").hidden, false);
  const row = get("postcard-list").children[0];
  assert.equal(row.tabIndex, 0);
  await row.emit("click");
  assert.equal(get("view-detail").hidden, false);
  assert.equal(get("view-edit").hidden, true);
  await get("detail-back").emit("click");
  await flush();
  await get("postcard-list").children[0].emit("keydown", { key: "Enter" });
  await flush();
  assert.equal(context.window.location.hash, `#postcards/${firstUuid}`);

  context.window.location.hash = "#data";
  await ui.windowListeners.hashchange();
  assert.equal(get("view-data").hidden, false);
  context.window.location.hash = `#postcards/${firstUuid}`;
  await ui.windowListeners.popstate();
  assert.equal(get("detail-title").textContent, "Postcard #42");

  context.fetch = async () => response({ id: 42, uuid: firstUuid, front_image_path: "", tags: [] });
  await run(`navigate("postcards/${firstUuid}")`);
  assert.equal(get("detail-photos").children.length, 1);
  assert.equal(get("detail-photos").children[0].children[1].textContent, "No image");
  assert.equal(get("detail-metadata").children.length, 0);

  context.fetch = async () => ({
    ok: false, status: 404, json: async () => ({ error: "postcard not found" }),
  });
  await run(`navigate("postcards/${secondUuid}")`);
  assert.equal(get("detail-content").hidden, true);
  assert.equal(get("detail-edit").hidden, true);
  assert.match(get("detail-status").textContent, /does not exist/);
  context.fetch = async () => { throw new Error("Network error"); };
  await run(`navigate("postcards/${firstUuid}")`);
  assert.match(get("detail-status").textContent, /could not be loaded/);
  run('applyLanguage("de")');
  assert.match(get("detail-status").textContent, /konnte nicht geladen/);

  for (const id of ["", "42", "0", "-1", "x", "42/edit", firstUuid.toUpperCase(),
    "b962a358-8899-1000-8999-6973bac5d599", "999999999999999999999"]) {
    context.window.location.hash = `#postcards/${id}`;
    await run("route()");
    assert.equal(get("detail-content").hidden, true);
    assert.equal(get("detail-status").textContent, "Dieser Postkartenlink ist ungültig.");
  }

  // Slow requests must not overwrite a different card or a view the user chose.
  let resolve;
  context.fetch = () => new Promise((done) => { resolve = done; });
  const slow = run(`navigate("postcards/${firstUuid}")`);
  assert.equal(get("detail-content").hidden, true);
  context.fetch = async () => response({ ...postcard, id: 43, uuid: secondUuid });
  await run(`navigate("postcards/${secondUuid}")`);
  resolve(response(postcard));
  await slow;
  assert.equal(get("detail-title").textContent, "Postkarte #43");
  context.fetch = () => new Promise((done) => { resolve = done; });
  const abandoned = run(`navigate("postcards/${firstUuid}")`);
  context.fetch = async () => response([]);
  await run('navigate("browse")');
  resolve(response(postcard));
  await abandoned;
  assert.equal(get("view-detail").hidden, true);
  assert.equal(get("detail-content").hidden, true);
  console.log("Detail page runtime checks passed.");
}

runTests().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
