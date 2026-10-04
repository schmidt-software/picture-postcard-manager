"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const staticDir = path.join(__dirname, "../app/static");

class Element {
  constructor() {
    this.dataset = {};
    this.attributes = {};
    this.style = {};
    this.listeners = {};
    this.children = [];
    this.textContent = "";
    this.value = "";
    this.hidden = false;
    this.files = [];
    this.classList = { toggle() {} };
  }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  setAttribute(name, value) { this.attributes[name] = value; }
  focus() { this.focused = true; }
  select() { this.selected = true; }
  click() { this.clicked = true; }
  showModal() { this.open = true; }
  addEventListener(name, callback, options = {}) {
    (this.listeners[name] ??= []).push({ callback, once: options.once });
  }
  async emit(name, event = {}) {
    const listeners = [...(this.listeners[name] || [])];
    this.listeners[name] = listeners.filter((listener) => !listener.once);
    await Promise.all(listeners.map(({ callback }) =>
      callback({ target: this, preventDefault() {}, ...event })));
  }
}

function setup(saved = null, blockedStorage = false, options = {}) {
  const elements = new Map();
  const all = [];
  // Only attributes needed by the application are modeled; no DOM dependency.
  const html = fs.readFileSync(path.join(staticDir, "index.html"), "utf8");
  for (const [, tag, attributes] of html.matchAll(/<(\w+)\b([^>]*)>/g)) {
    const el = new Element();
    el.tag = tag;
    for (const [, name, value] of attributes.matchAll(/([\w-]+)="([^"]*)"/g)) {
      el.attributes[name] = value;
      if (name.startsWith("data-")) {
        const key = name.slice(5).replace(/-(\w)/g, (_, letter) => letter.toUpperCase());
        el.dataset[key] = value;
      } else {
        el[name] = value;
      }
    }
    el.hidden = /\bhidden\b/.test(attributes);
    el.required = /\brequired\b/.test(attributes);
    if (el.id) elements.set(`#${el.id}`, el);
    all.push(el);
  }
  const postcardForm = elements.get("#postcard-form");
  postcardForm.elements = Object.fromEntries(all
    .filter((el) => el.name && ["input", "textarea"].includes(el.tag)
      && !["file", "radio"].includes(el.type))
    .map((el) => [el.name, el]));
  postcardForm.reset = () => {
    for (const el of Object.values(postcardForm.elements)) el.value = "";
  };
  const importForm = elements.get("#import-form");
  importForm.elements = { file: elements.get("#import-file"), mode: { value: "append" } };
  importForm.reset = () => {
    importForm.elements.file.files = [];
    importForm.elements.mode.value = "append";
  };
  const storage = new Map(saved === null ? [] : [["picture-postcard-manager-language", saved]]);
  const requests = [];
  const location = new URL(options.url ?? "http://127.0.0.1:8000/");
  const windowListeners = {};
  const context = vm.createContext({
    window: {
      location,
      history: { pushState(state, title, url) { location.href = String(url); } },
      addEventListener(name, callback) { windowListeners[name] = callback; },
    },
    navigator: {},
    URL,
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
    localStorage: {
      getItem(key) {
        if (blockedStorage) throw new Error("Storage denied");
        return storage.get(key) ?? null;
      },
      setItem(key, value) {
        if (blockedStorage) throw new Error("Storage denied");
        storage.set(key, value);
      },
    },
    FormData: class {
      constructor(form) { this.form = form; }
      *[Symbol.iterator]() {
        for (const [key, el] of Object.entries(this.form.elements)) yield [key, el.value];
      }
    },
    fetch: async (url, requestOptions) => {
      requests.push({ url, options: requestOptions });
      if (options.fetch) return options.fetch(url, requestOptions);
      return { ok: true, status: 200, json: async () => [] };
    },
    setTimeout: () => 1,
    clearTimeout() {},
  });
  for (const file of ["languages.js", "app.js"]) {
    vm.runInContext(fs.readFileSync(path.join(staticDir, file), "utf8"), context);
  }
  return {
    context, elements, all, storage, requests, postcardForm, importForm, windowListeners,
    run: (source) => vm.runInContext(source, context),
    get: (id) => elements.get(`#${id}`),
  };
}

async function runTests() {
  for (const [saved, expected] of [[null, "en"], ["de", "de"], ["unknown", "en"], ["toString", "en"]]) {
    const ui = setup(saved);
    assert.equal(ui.context.document.documentElement.lang, expected);
    assert.equal(ui.storage.get("picture-postcard-manager-language"), expected);
  }
  const blocked = setup("de", true);
  blocked.run('applyLanguage("de")');
  assert.equal(blocked.context.document.documentElement.lang, "de");

  const ui = setup();
  const { run, get, postcardForm, importForm, context, requests } = ui;
  const primary = Object.values(postcardForm.elements).find((el) => el.required);
  const secondary = Object.values(postcardForm.elements).find((el) =>
    el.name !== "id" && el !== primary);
  const validationError = get(primary.attributes["aria-describedby"]);
  const requiredMessage = () => run('translate("requiredFrontImage")');
  await new Promise(setImmediate);
  run('applyLanguage("de")');
  for (const el of ui.all) {
    if (el.dataset.i18n) assert.equal(el.textContent, context.window.UI_TRANSLATIONS.de[el.dataset.i18n]);
    if (el.dataset.i18nPlaceholder) assert.equal(el.placeholder, context.window.UI_TRANSLATIONS.de[el.dataset.i18nPlaceholder]);
    if (el.dataset.i18nAriaLabel) assert.equal(el.attributes["aria-label"], context.window.UI_TRANSLATIONS.de[el.dataset.i18nAriaLabel]);
  }
  assert.equal(get("language-select").children.length, 2);
  assert.equal(get("file-name").textContent, "Keine Datei ausgewählt.");
  assert.equal(run('translate("imported", {count: 0})'), "0 Postkarten importiert.");
  delete context.window.UI_TRANSLATIONS.de.saved;
  assert.equal(run('translate("saved")'), "Postcard saved.");
  context.window.UI_TRANSLATIONS.de.saved = "Postkarte gespeichert.";
  assert.equal(run('translate("missingKey")'), "missingKey");
  assert.equal(run('translate("editPostcard")'), "Postkarte #{id} bearbeiten");

  context.samplePostcard = {
    id: 7, [primary.name]: "  User <text>  ", [secondary.name]: "User content\n unchanged",
  };
  run("openForm(samplePostcard)");
  get("search").value = "User search";
  importForm.elements.file.files = [{ name: "Meine Postkarten.json", text: async () => '{"postcards":[]}' }];
  run('applyLanguage("en")');
  assert.equal(get("form-title").textContent, "Edit postcard #7");
  assert.equal(primary.value, "  User <text>  ");
  assert.equal(secondary.value, "User content\n unchanged");
  assert.equal(get("search").value, "User search");
  assert.equal(get("file-name").textContent, "Meine Postkarten.json");

  const originalRequests = requests.length;
  primary.value = "";
  await postcardForm.emit("submit");
  assert.equal(requests.length, originalRequests);
  assert.equal(validationError.textContent, requiredMessage());
  assert.equal(primary.focused, true);
  assert.equal(primary.attributes["aria-invalid"], "true");
  run('applyLanguage("de")');
  assert.equal(validationError.textContent, requiredMessage());
  primary.value = "  User <text>  ";
  await primary.emit("input");
  assert.equal(validationError.hidden, true);

  context.fetch = async (url, options) => {
    requests.push({ url, options });
    return { ok: true, status: 200, json: async () => url.startsWith("/api/import") ? { imported: 2 } : [] };
  };
  await postcardForm.emit("submit");
  const saved = requests.find((request) => request.options.method === "PUT");
  const savedData = JSON.parse(saved.options.body);
  assert.equal(savedData[primary.name], "  User <text>  ");
  assert.equal(savedData[secondary.name], "User content\n unchanged");
  assert.equal(get("message").textContent, "Postkarte gespeichert.");
  run('applyLanguage("en")');
  assert.equal(get("message").textContent, "Postcard saved.");
  get("message").hidden = true;
  run('applyLanguage("de")');
  assert.equal(get("message").hidden, true);

  for (const [raw, key] of Object.entries(run("apiErrorKeys"))) {
    context.rawError = raw;
    assert.equal(run("formatApiError(rawError)"), context.window.UI_TRANSLATIONS.de[key]);
  }
  run('showApiError(new Error("invalid JSON: Expecting value at line 1"))');
  assert.equal(get("message").textContent,
    "Fehler: Die Datei enthält kein gültiges JSON: Expecting value at line 1");
  run('applyLanguage("en")');
  assert.equal(get("message").textContent,
    "Error: The file does not contain valid JSON: Expecting value at line 1");
  run('applyLanguage("de")');
  assert.equal(run('formatApiError("unknown import fields: extra, legacy")'),
    "Der Import enthält unbekannte Felder: extra, legacy.");
  assert.equal(run('formatApiError("unsupported import schema_version: 99")'),
    "Die Import-Schemaversion 99 wird nicht unterstützt.");
  assert.equal(run('formatApiError("postcard 2: front_image_path is required and must be a non-empty string")'),
    "Postkarte 2 konnte nicht importiert werden: Der Bildpfad der Vorderseite ist erforderlich und darf nicht leer sein.");
  run('applyLanguage("en")');
  for (const message of ["Failed to fetch", "NetworkError", "Internal Server Error", "Unexpected token"]) {
    context.fetch = async () => { throw new Error(message); };
    await run("loadList()");
    assert.equal(get("message").textContent, "Error: The request failed. Please try again.");
    assert.equal(get("message").className, "error");
  }
  context.fetch = async () => ({
    ok: false, status: 404, json: async () => ({ error: "postcard not found" }),
  });
  await run("loadList()");
  assert.equal(get("message").textContent, "Error: Postcard not found.");

  importForm.elements.file.files = [];
  await importForm.emit("submit");
  assert.equal(get("file-error").textContent, "Please choose a JSON file.");
  assert.equal(get("choose-file").focused, true);
  run('applyLanguage("de")');
  assert.equal(get("file-error").textContent, "Bitte eine JSON-Datei auswählen.");
  await get("choose-file").emit("click");
  assert.equal(get("import-file").clicked, true);
  importForm.elements.file.files = [{ name: "User file.json", text: async () => { throw new Error("OS error"); } }];
  await get("import-file").emit("change");
  assert.equal(get("file-error").hidden, true);
  await importForm.emit("submit");
  assert.equal(get("message").textContent, "Fehler: Die ausgewählte Datei konnte nicht gelesen werden.");

  const actions = [];
  context.fetch = async (url, options) => {
    actions.push({ url, options });
    return { ok: true, status: options.method === "DELETE" ? 204 : 200,
      json: async () => options.method === "POST" ? { imported: 2 } : [] };
  };
  const dialog = get("confirmation");
  let pending = get("delete").emit("click");
  assert.equal(dialog.open, true);
  assert.equal(get("confirmation-text").textContent, "Diese Postkarte löschen?");
  assert.equal(get("confirm-action").textContent, "Löschen");
  run('applyLanguage("en")');
  assert.equal(get("confirmation-text").textContent, "Delete this postcard?");
  assert.equal(get("confirm-action").textContent, "Delete");
  dialog.returnValue = "cancel";
  await dialog.emit("close");
  await pending;
  assert.equal(actions.length, 0);
  pending = get("delete").emit("click");
  dialog.returnValue = "confirm";
  await dialog.emit("close");
  await pending;
  assert.equal(actions[0].options.method, "DELETE");
  assert.equal(get("message").textContent, "Postcard deleted.");

  importForm.elements.file.files = [{ name: "User file.json", text: async () => '{"postcards":[]}' }];
  importForm.elements.mode.value = "replace";
  pending = importForm.emit("submit");
  assert.equal(get("confirmation-text").textContent, "Replace ALL existing postcards?");
  dialog.returnValue = "";
  await dialog.emit("close");
  await pending;
  assert.equal(actions.filter((action) => action.options.method === "POST").length, 0);
  run('applyLanguage("de")');
  pending = importForm.emit("submit");
  assert.equal(get("confirm-action").textContent, "Ersetzen");
  dialog.returnValue = "confirm";
  await dialog.emit("close");
  await pending;
  assert.equal(get("message").textContent, "2 Postkarten importiert.");
  assert.equal(get("file-name").textContent, "Keine Datei ausgewählt.");
  assert.equal(actions.find((action) => action.options.method === "POST").options.body, '{"postcards":[]}');

  const content = {
    id: 42, uuid: "b962a358-8899-4000-8999-6973bac5d599",
    [primary.name]: "Save <script>", [secondary.name]: "Löschen / Delete",
    updated_at: "2026-10-04",
  };
  context.fetch = async (url) => ({
    ok: true, status: 200,
    json: async () => url === `/api/postcards/by-uuid/${content.uuid}` ? content : [content],
  });
  await run("loadList()");
  const cells = get("postcard-list").children[0].children.map((el) => el.textContent);
  assert.equal(cells[0], 42);
  assert.equal(cells.at(-1), content.updated_at);
  await get("postcard-list").children[0].emit("click");
  assert.equal(get("detail-title").textContent, "Postkarte #42");
  await get("detail-edit").emit("click");
  assert.equal(get("form-title").textContent, "Postkarte #42 bearbeiten");
  assert.equal(primary.value, content[primary.name]);
  console.log("Localization runtime checks passed.");
}

module.exports = { setup };
if (require.main === module) {
  runTests().catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
}
