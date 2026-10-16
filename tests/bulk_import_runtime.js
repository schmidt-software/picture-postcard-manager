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
  const fetched = [];
  context.fetch = async (url, options) => {
    fetched.push(url);
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

  // Mixed batch: successes, a server-side upload failure, a back-only file
  // and an unsupported type; failures never abort the remaining files.
  context.okFiles = [
    file("pair-front.jpg"), file("pair-back.jpg"),
    file("single.jpg"), file("bad.jpg"), file("orphan-back.jpg"),
    { name: "notes.txt", type: "text/plain", size: 10 },
  ];
  const outcome = await run("runBulkImport(okFiles)");
  assert.equal(outcome.created, 2);
  // Upload failures, unsupported types and back-only files all count as failed.
  assert.equal(outcome.failed, 3);
  assert.equal(posted.length, 2);
  assert.ok(posted[0].front_image_path.startsWith("/images/"));
  assert.ok(posted[0].back_image_path.startsWith("/images/"));
  assert.equal(posted[1].back_image_path, undefined);
  const texts = outcome.results.map((r) => run("translate")(r.key, r.params));
  assert.ok(texts.some((t) => t.includes("pair-front.jpg + pair-back.jpg: postcard #1 created.")), texts);
  assert.ok(texts.some((t) => t.includes("single.jpg: postcard #2 created.")), texts);
  assert.ok(texts.some((t) => t.includes("bad.jpg:")), texts);
  assert.ok(texts.some((t) => t.includes("orphan-back.jpg:")), texts);
  assert.ok(texts.some((t) =>
    t.includes("notes.txt: This image type is not supported.")), texts);
  // The summary count matches the number of failed result rows.
  assert.equal(outcome.results.filter((r) => r.failed).length, outcome.failed);
  assert.ok(outcome.results.find((r) => r.params.name === "orphan-back.jpg").failed);

  // Form flow: no files -> validation error; with files -> summary and list.
  await get("bulk-form").emit("submit");
  assert.equal(get("bulk-error").hidden, false);
  assert.equal(get("bulk-error").textContent, "Please choose at least one image file.");

  get("bulk-files").files = context.okFiles;
  await get("bulk-files").emit("change");
  assert.equal(get("bulk-error").hidden, true);
  assert.equal(get("bulk-file-count").textContent, "6 file(s) selected.");
  await get("bulk-form").emit("submit");
  assert.equal(get("bulk-summary").textContent, "2 postcard(s) created, 3 file(s) failed.");
  assert.equal(get("bulk-results").children.length, 5);
  assert.equal(get("bulk-results").children.filter((li) => li.className === "bulk-failed").length, 3);
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

  // Client-side validation and server errors are localized: in German, each
  // failure detail uses the German translation, never the English raw text.
  run('applyLanguage("de")');
  context.deFiles = [
    { name: "leer.jpg", type: "image/jpeg", size: 0 },
    { name: "riesig.jpg", type: "image/jpeg", size: 21 * 1024 * 1024 },
    { name: "text.txt", type: "text/plain", size: 10 },
    file("bad.jpg"),
    file("verwaist-back.jpg"),
  ];
  const german = await run("runBulkImport(deFiles)");
  assert.equal(german.created, 0);
  assert.equal(german.failed, 5);
  const deTexts = german.results.map((r) => run("translate")(r.key, r.params));
  const expectDetail = (name, detail) => {
    const text = deTexts.find((t) => t.startsWith(`${name}:`));
    assert.equal(text, `${name}: ${detail}`, deTexts);
  };
  expectDetail("leer.jpg", "Die ausgewählte Bilddatei ist leer.");
  expectDetail("riesig.jpg", "Das Bild ist zu groß. Die maximale Größe beträgt 20 MiB.");
  expectDetail("text.txt",
    "Dieser Bildtyp wird nicht unterstützt. Bitte eine PNG-, JPEG-, GIF- oder WebP-Datei auswählen.");
  // Server-side upload errors go through the shared API error map (same
  // convention as the single-image upload status).
  expectDetail("bad.jpg", "Der Dateiinhalt ist kein gültiges PNG-, JPEG-, GIF- oder WebP-Bild.");
  expectDetail("verwaist-back.jpg", "Keine passende Vorderseite ausgewählt.");
  run('applyLanguage("en")');

  // Returning to the overview after a bulk import refetches the list from the
  // server with the usual pagination parameters, so new postcards show up.
  const before = fetched.length;
  await run('navigate("browse")');
  const listUrl = fetched.slice(before).find((url) => url.startsWith("/api/postcards?"));
  assert.ok(listUrl, "overview was not reloaded");
  assert.match(listUrl, /limit=\d+/);
  assert.match(listUrl, /offset=0/);

  await refreshTests();

  console.log("Bulk import runtime checks passed.");
}

// New postcards may carry the first use of a year/tag value, so
// the filter dropdowns must refresh after a bulk import. Returning to the
// overview reloads them on entry, but the import runs asynchronously: the
// user may already be back on the overview when it finishes, so the bulk
// handler refreshes the dropdowns and the list itself. Without that refresh
// in the submit handler every check below the release fails.
async function refreshTests() {
  const ui = setup();
  const { run, get, context } = ui;
  const flush = () => new Promise(setImmediate);
  let options = { year: ["1910"], tag: ["street"] };
  let releasePost;
  const postGate = new Promise((resolve) => (releasePost = resolve));
  context.fetch = async (url, opts = {}) => {
    if (url === "/api/images") {
      return { ok: true, status: 201,
        json: async () => ({ path: `/images/${"b".repeat(32)}.jpg` }) };
    }
    if (url === "/api/postcards" && opts.method === "POST") {
      await postGate; // The import finishes only when the test releases it.
      options = { ...options, tag: [...options.tag, "mountain"] };
      return { ok: true, status: 201, json: async () => ({ id: 1 }) };
    }
    return { ok: true, status: 200,
      json: async () => (url === "/api/postcards/filters" ? options : []) };
  };
  const values = (key) =>
    get(`filter-${key}`).children.map((option) => option.textContent).slice(1);

  // Start a bulk import on the data view, then return to the overview while
  // the import is still running: the dropdowns load before the postcard exists.
  await run('navigate("data")');
  get("bulk-files").files = [file("alps.jpg")];
  const importing = get("bulk-form").emit("submit");
  await flush();
  await run('navigate("browse")');
  await flush();
  assert.deepEqual(values("tag"), ["street"]);
  get("filter-tag").value = "street";
  await get("filter-tag").emit("change");

  // The import finishes while the overview is visible: the new values must
  // appear without another navigation, and an active selection survives.
  releasePost();
  await importing;
  await flush();
  assert.ok(values("tag").includes("mountain"),
    "bulk-imported tag must appear in the filter dropdown");
  assert.equal(get("filter-tag").value, "street",
    "selection must survive the refresh");
}

runTests().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
