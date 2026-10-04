"use strict";

// Runtime checks for the image upload controls, using a minimal DOM stand-in.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const staticDir = path.join(__dirname, "../app/static");

class Element {
  constructor() {
    this.dataset = {};
    this.attributes = {};
    this.listeners = {};
    this.children = [];
    this.textContent = "";
    this.value = "";
    this.hidden = false;
    this.disabled = false;
    this.files = [];
    this.classList = { toggle() {} };
  }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  setAttribute(name, value) { this.attributes[name] = value; }
  focus() { this.focused = true; }
  click() { this.clicks = (this.clicks ?? 0) + 1; }
  showModal() { this.open = true; }
  addEventListener(name, callback) { (this.listeners[name] ??= []).push(callback); }
  emit(name) {
    return Promise.all((this.listeners[name] || []).map((callback) =>
      callback({ target: this, preventDefault() {} })));
  }
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((done, failed) => { resolve = done; reject = failed; });
  return { promise, resolve, reject };
}

function setup() {
  const elements = new Map();
  const all = [];
  const html = fs.readFileSync(path.join(staticDir, "index.html"), "utf8");
  for (const [, tag, attributes] of html.matchAll(/<(\w+)\b([^>]*)>/g)) {
    const el = new Element();
    el.tag = tag;
    for (const [, name, value] of attributes.matchAll(/([\w-]+)="([^"]*)"/g)) {
      el.attributes[name] = value;
      if (name.startsWith("data-")) {
        el.dataset[name.slice(5).replace(/-(\w)/g, (_, c) => c.toUpperCase())] = value;
      } else {
        el[name] = value;
      }
    }
    el.hidden = /\bhidden\b/.test(attributes);
    if (el.id) elements.set(`#${el.id}`, el);
    all.push(el);
  }
  const form = elements.get("#postcard-form");
  form.elements = Object.fromEntries(all
    .filter((el) => el.name && ["input", "textarea"].includes(el.tag)
      && !["file", "radio"].includes(el.type))
    .map((el) => [el.name, el]));
  form.reset = () => Object.values(form.elements).forEach((el) => (el.value = ""));
  const importForm = elements.get("#import-form");
  importForm.elements = { file: elements.get("#import-file"), mode: { value: "append" } };
  const requests = [];
  const uploads = [];
  const context = vm.createContext({
    window: {},
    document: {
      documentElement: {},
      querySelector: (selector) => elements.get(selector),
      querySelectorAll: (selector) => {
        if (selector === "nav button") return all.filter((el) => el.dataset.view);
        if (selector === ".view") return all.filter((el) => el.class === "view");
        const attribute = selector.slice(1, -1);
        return all.filter((el) => Object.hasOwn(el.attributes, attribute));
      },
      createElement: () => new Element(),
    },
    localStorage: { getItem: () => null, setItem() {} },
    FormData: class {
      constructor(f) { this.form = f; }
      *[Symbol.iterator]() {
        for (const [key, el] of Object.entries(this.form.elements)) yield [key, el.value];
      }
    },
    fetch: (url, options = {}) => {
      requests.push({ url, options });
      if (url === "/api/images") {
        const upload = deferred();
        uploads.push({ options, ...upload });
        return upload.promise;
      }
      return Promise.resolve({ ok: true, status: 200, json: async () => [] });
    },
    setTimeout: () => 1,
    clearTimeout() {},
  });
  for (const file of ["languages.js", "app.js"]) {
    vm.runInContext(fs.readFileSync(path.join(staticDir, file), "utf8"), context);
  }
  const get = (id) => elements.get(`#${id}`);
  return {
    context, form, requests, uploads, get,
    run: (source) => vm.runInContext(source, context),
    front: form.elements.front_image_path,
    back: form.elements.back_image_path,
  };
}

const flush = () => new Promise(setImmediate);
const ok = (body, status = 201) => ({ ok: true, status, json: async () => body });
const fail = (status, error) => ({ ok: false, status, json: async () => ({ error }) });
const png = (name = "card.png", size = 100, type = "image/png") => ({ name, size, type });

async function choose(ui, side, file) {
  ui.get(`${side}-image-file`).files = [file];
  const done = ui.get(`${side}-image-file`).emit("change");
  await flush();
  return { done };
}

async function runTests() {
  let ui = setup();
  const { get, run, front, back, uploads, requests } = ui;
  await flush();
  run("openForm({id: 3, front_image_path: 'old/front.jpg', back_image_path: 'old/back.jpg'})");

  // Each path has its own picker, which opens only its own hidden file input.
  for (const side of ["front", "back"]) {
    const input = get(`${side}-image-file`);
    assert.equal(input.hidden, true);
    assert.equal(input.type, "file");
    assert.equal(input.accept, "image/png,image/jpeg,image/gif,image/webp");
    assert.equal(input.name, undefined);
    await get(`choose-${side}-image`).emit("click");
    assert.equal(input.clicks, 1);
  }
  assert.equal(get("front-image-file").clicks, 1);
  assert.equal(get("choose-front-image").textContent, "Choose front image");

  // Binary upload keeps the image Content-Type and disables saving while pending.
  const frontFile = png();
  let done = (await choose(ui, "front", frontFile)).done;
  assert.equal(uploads.length, 1);
  assert.equal(requests.at(-1).url, "/api/images");
  assert.equal(uploads[0].options.method, "POST");
  assert.equal(uploads[0].options.headers["Content-Type"], "image/png");
  assert.equal(uploads[0].options.body, frontFile);
  assert.equal(get("front-image-file").value, "");
  assert.equal(get("save").disabled, true);
  assert.equal(get("choose-front-image").disabled, true);
  assert.equal(get("choose-back-image").disabled, false);
  assert.equal(get("front-image-status").textContent, "Uploading image…");
  assert.equal(ui.form.attributes["aria-busy"], "true");

  // Saving is refused while an upload is pending.
  const before = requests.length;
  await ui.form.emit("submit");
  assert.equal(requests.length, before);
  assert.equal(get("message").textContent, "Error: Please wait until the image upload has finished.");

  // Concurrent back upload; completion order does not mix up fields.
  const backDone = (await choose(ui, "back", png("b.webp", 10, "image/webp"))).done;
  assert.equal(uploads[1].options.headers["Content-Type"], "image/webp");
  uploads[1].resolve(ok({ path: "/images/" + "b".repeat(32) + ".webp" }));
  await backDone;
  assert.equal(back.value, "/images/" + "b".repeat(32) + ".webp");
  assert.equal(front.value, "old/front.jpg");
  assert.equal(get("save").disabled, true);
  assert.equal(get("choose-back-image").disabled, false);
  uploads[0].resolve(ok({ path: "/images/" + "a".repeat(32) + ".png" }));
  await done;
  assert.equal(front.value, "/images/" + "a".repeat(32) + ".png");
  assert.equal(back.value, "/images/" + "b".repeat(32) + ".webp");
  assert.equal(get("save").disabled, false);
  assert.equal(get("choose-front-image").disabled, false);
  assert.equal(get("front-image-status").textContent, "Image uploaded.");
  assert.equal(ui.form.attributes["aria-busy"], "false");

  // The uploaded paths are saved with the postcard.
  await ui.form.emit("submit");
  const put = requests.find((r) => r.options.method === "PUT");
  assert.equal(put.options.headers["Content-Type"], "application/json");
  assert.deepEqual(
    [JSON.parse(put.options.body).front_image_path, JSON.parse(put.options.body).back_image_path],
    ["/images/" + "a".repeat(32) + ".png", "/images/" + "b".repeat(32) + ".webp"]);

  // Server errors keep the previous path, are localized and restore controls.
  run("openForm({id: 4, front_image_path: 'keep/front.png', back_image_path: 'keep/back.png'})");
  run('applyLanguage("de")');
  for (const [response, message] of [
    [fail(415, "image content is not a valid PNG, JPEG, GIF or WebP file"),
      "Der Dateiinhalt ist kein gültiges PNG-, JPEG-, GIF- oder WebP-Bild."],
    [fail(500, "image could not be stored"),
      "Der Server konnte das Bild nicht speichern. Bitte erneut versuchen oder den Administrator kontaktieren."],
    [fail(413, "image is too large (maximum 20 MiB)"),
      "Das Bild ist zu groß. Die maximale Größe beträgt 20 MiB."],
    [ok({}), "Die Anfrage ist fehlgeschlagen. Bitte erneut versuchen."],
    [new TypeError("Failed to fetch"),
      "Die Anfrage ist fehlgeschlagen. Bitte erneut versuchen."],
  ]) {
    done = (await choose(ui, "front", png())).done;
    if (response instanceof Error) uploads.at(-1).reject(response);
    else uploads.at(-1).resolve(response);
    await done;
    assert.equal(front.value, "keep/front.png");
    assert.equal(back.value, "keep/back.png");
    assert.equal(get("front-image-status").textContent,
      `Hochladen fehlgeschlagen: ${message} Der bisherige Pfad wurde beibehalten.`);
    assert.equal(get("front-image-status").className, "upload-error");
    assert.equal(get("save").disabled, false);
    assert.equal(get("choose-front-image").disabled, false);
  }
  run('applyLanguage("en")');
  assert.equal(get("front-image-status").textContent,
    "Image upload failed: The request failed. Please try again. The previous path was kept.");
  assert.equal(get("choose-back-image").textContent, "Choose back image");

  // Client-side checks reject files before uploading them.
  const count = uploads.length;
  for (const [file, message] of [
    [png("huge.png", 20 * 1024 * 1024 + 1), "The image is too large. The maximum size is 20 MiB."],
    [png("x.svg", 10, "image/svg+xml"),
      "This image type is not supported. Please choose a PNG, JPEG, GIF or WebP file."],
    [png("x", 10, ""), "This image type is not supported. Please choose a PNG, JPEG, GIF or WebP file."],
    [png("empty.png", 0), "The selected image file is empty."],
  ]) {
    await choose(ui, "back", file);
    assert.equal(back.value, "keep/back.png");
    assert.equal(get("back-image-status").textContent,
      `Image upload failed: ${message} The previous path was kept.`);
    assert.equal(get("save").disabled, false);
  }
  assert.equal(uploads.length, count);
  // Cancelling the native picker changes nothing.
  get("back-image-file").files = [];
  await get("back-image-file").emit("change");
  assert.equal(uploads.length, count);

  // A stale upload never writes into a form that was switched, cancelled or reset.
  for (const action of [
    "openForm({id: 5, front_image_path: 'other.png'})",
    "openForm()",
    "showView('browse')",
  ]) {
    run("openForm({id: 4, front_image_path: 'keep/front.png'})");
    done = (await choose(ui, "front", png())).done;
    assert.equal(get("save").disabled, true);
    run(action);
    assert.equal(get("save").disabled, false);
    assert.equal(get("choose-front-image").disabled, false);
    assert.equal(get("front-image-status").textContent, "");
    const value = front.value;
    uploads.at(-1).resolve(ok({ path: "/images/" + "c".repeat(32) + ".png" }));
    await done;
    assert.equal(front.value, value);
    assert.equal(get("save").disabled, false);
    assert.equal(get("front-image-status").textContent, "");
  }
  run("openForm({id: 4, front_image_path: 'keep/front.png'})");
  done = (await choose(ui, "back", png())).done;
  await get("cancel").emit("click");
  run("openForm({id: 4, front_image_path: 'keep/front.png'})");
  const replacement = (await choose(ui, "back", png())).done;
  uploads.at(-2).resolve(ok({ path: "/images/" + "d".repeat(32) + ".png" }));
  await done;
  assert.equal(back.value, "");
  assert.equal(get("save").disabled, true);
  uploads.at(-1).resolve(ok({ path: "/images/" + "e".repeat(32) + ".png" }));
  await replacement;
  assert.equal(back.value, "/images/" + "e".repeat(32) + ".png");

  // Manual entry stays possible and wins over a pending upload.
  done = (await choose(ui, "front", png())).done;
  front.value = "manual/front.jpg";
  await front.emit("input");
  assert.equal(get("save").disabled, false);
  uploads.at(-1).resolve(ok({ path: "/images/" + "f".repeat(32) + ".png" }));
  await done;
  assert.equal(front.value, "manual/front.jpg");

  // An upload fills a missing required front path and clears its validation error.
  ui = setup();
  await flush();
  ui.run("openForm()");
  await ui.form.emit("submit");
  assert.equal(ui.get("front-image-error").hidden, false);
  done = (await choose(ui, "front", png())).done;
  ui.uploads[0].resolve(ok({ path: "/images/" + "9".repeat(32) + ".png" }));
  await done;
  assert.equal(ui.front.value, "/images/" + "9".repeat(32) + ".png");
  assert.equal(ui.get("front-image-error").hidden, true);
  assert.equal(ui.front.attributes["aria-invalid"], "false");
  await ui.form.emit("submit");
  const post = ui.requests.find((r) => r.url === "/api/postcards" && r.options.method === "POST");
  assert.equal(JSON.parse(post.options.body).front_image_path, "/images/" + "9".repeat(32) + ".png");
  assert.equal(JSON.parse(post.options.body).back_image_path, "");
  console.log("Image upload runtime checks passed.");
}

runTests().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
