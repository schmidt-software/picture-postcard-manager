"use strict";

const assert = require("node:assert/strict");
const { setup } = require("./i18n_runtime");

function file(name, type = "image/jpeg", size = 100) {
  return { name, type, size };
}

async function runTests() {
  const ui = setup();
  const { run, get, context } = ui;

  // Grouping: front/back pairs by base name, singles, back-only, duplicates.
  context.bulkFiles = [
    file("alps-front.jpg"), file("alps-back.jpg"),
    file("Berlin_FRONT.png", "image/png"), file("city.jpg"),
    file("lake-back.jpg"),
    file("dup-front.jpg"), file("dup-front.png", "image/png"),
  ];
  const groups = run("groupBulkFiles(bulkFiles)");
  const names = groups.map((g) => [g.front?.name ?? null, g.back?.name ?? null]);
  assert.equal(JSON.stringify(names), JSON.stringify([
    ["alps-front.jpg", "alps-back.jpg"],
    ["Berlin_FRONT.png", null],
    ["dup-front.jpg", null],
    [null, "lake-back.jpg"],
    ["city.jpg", null],
    ["dup-front.png", null],
  ]));

  // Bulk run: uploads each file, creates postcards, reports per file.
  let nextId = 1;
  const posted = [];
  context.fetch = async (url, options) => {
    if (url === "/api/images") {
      const name = options.body.name;
      if (name === "bad.jpg") {
        return { ok: false, status: 415,
          json: async () => ({ error: "image content is not a valid PNG, JPEG, GIF or WebP file" }) };
      }
      return { ok: true, status: 201, json: async () => ({ path: `/images/${"a".repeat(32)}.jpg` }) };
    }
    if (url === "/api/postcards") {
      posted.push(JSON.parse(options.body));
      return { ok: true, status: 201, json: async () => ({ id: nextId++ }) };
    }
    return { ok: true, status: 200, json: async () => [] };
  };

  context.okFiles = [
    file("pair-front.jpg"), file("pair-back.jpg"),
    file("single.jpg"), file("bad.jpg"), file("orphan-back.jpg"),
  ];
  const outcome = await run("runBulkImport(okFiles)");
  assert.equal(outcome.created, 2);
  assert.equal(outcome.failed, 1);
  assert.equal(posted.length, 2);
  assert.ok(posted[0].front_image_path.startsWith("/images/"));
  assert.ok(posted[0].back_image_path.startsWith("/images/"));
  assert.equal(posted[1].back_image_path, undefined);
  const texts = outcome.results.map((r) => run("translate")(r.key, r.params));
  assert.ok(texts.some((t) => t.includes("pair-front.jpg + pair-back.jpg: postcard #1 created.")), texts);
  assert.ok(texts.some((t) => t.includes("single.jpg: postcard #2 created.")), texts);
  assert.ok(texts.some((t) => t.includes("bad.jpg:")), texts);
  assert.ok(texts.some((t) => t.includes("orphan-back.jpg:")), texts);

  // Form flow: no files -> validation error; with files -> summary and list.
  await get("bulk-form").emit("submit");
  assert.equal(get("bulk-error").hidden, false);
  assert.equal(get("bulk-error").textContent, "Please choose at least one image file.");

  get("bulk-files").files = context.okFiles;
  await get("bulk-files").emit("change");
  assert.equal(get("bulk-error").hidden, true);
  assert.equal(get("bulk-file-count").textContent, "5 file(s) selected.");
  await get("bulk-form").emit("submit");
  assert.equal(get("bulk-summary").textContent, "2 postcard(s) created, 1 file(s) failed.");
  assert.equal(get("bulk-results").children.length, 4);
  assert.equal(get("bulk-start").disabled, false);

  // Oversized and empty files fail client-side without aborting others.
  context.sizeFiles = [
    { name: "huge.jpg", type: "image/jpeg", size: 21 * 1024 * 1024 },
    { name: "empty.jpg", type: "image/jpeg", size: 0 },
    file("fine.jpg"),
  ];
  const sized = await run("runBulkImport(sizeFiles)");
  assert.equal(sized.created, 1);
  assert.equal(sized.failed, 2);

  console.log("Bulk import runtime checks passed.");
}

runTests().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
