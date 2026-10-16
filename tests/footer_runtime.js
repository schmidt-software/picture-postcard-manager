"use strict";

// Runtime checks for the shared footer version display (issue #44):
// rendering from /api/version, localization, hostile payloads staying plain
// text, fallback on fetch errors, and visibility across SPA views.

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { setup } = require("./i18n_runtime");

const response = (data) => ({ ok: true, status: 200, json: async () => data });
const flush = () => new Promise(setImmediate);
const uuid = "b962a358-8899-4000-8999-6973bac5d599";

const postcard = {
  id: 42, uuid, front_image_path: "/images/front.png",
  place: "Place", region: "Region", year: "1905", description: "Text", tags: [],
};

async function runTests() {
  // The version renders with the localized label in both languages.
  let ui = setup(null, false, {
    fetch: async (url) => response(url === "/api/version" ? { version: "0.1.0" } : []),
  });
  await flush();
  assert.ok(ui.requests.some((request) => request.url === "/api/version"));
  assert.equal(ui.get("app-version").textContent, "Version 0.1.0");
  ui.run('applyLanguage("de")');
  assert.equal(ui.get("app-version").textContent, "Version 0.1.0");
  ui.run('applyLanguage("en")');
  assert.equal(ui.get("app-version").textContent, "Version 0.1.0");

  // The initial list request still comes first; the footer never delays it.
  assert.equal(ui.requests[0].url.startsWith("/api/postcards"), true, ui.requests[0].url);

  // The dev fallback value renders unchanged.
  ui = setup(null, false, {
    fetch: async (url) => response(url === "/api/version" ? { version: "dev" } : []),
  });
  await flush();
  assert.equal(ui.get("app-version").textContent, "Version dev");

  // A hostile payload is rendered as inert text via textContent, and the
  // footer module never touches innerHTML/outerHTML/insertAdjacentHTML.
  const payload = "<img src=x onerror=alert(1)><script>alert(1)</script>";
  ui = setup(null, false, {
    fetch: async (url) => response(url === "/api/version" ? { version: payload } : []),
  });
  await flush();
  assert.equal(ui.get("app-version").textContent, `Version ${payload}`);
  const source = fs.readFileSync(
    path.join(__dirname, "../app/static/js/footer.js"), "utf8");
  assert.doesNotMatch(source, /innerHTML|outerHTML|insertAdjacentHTML|document\.write/);

  // A failing version request leaves the footer empty and the app working.
  ui = setup(null, false, {
    fetch: async (url) => {
      if (url === "/api/version") throw new Error("Failed to fetch");
      return response([]);
    },
  });
  await flush();
  assert.equal(ui.get("app-version").textContent, "");
  assert.equal(ui.get("message").hidden, true);

  // A malformed response (non-string version) also falls back to empty.
  ui = setup(null, false, {
    fetch: async (url) => response(url === "/api/version" ? { version: 42 } : []),
  });
  await flush();
  assert.equal(ui.get("app-version").textContent, "");

  // The same footer element serves the overview and the detail page: it is
  // outside the view sections and stays rendered when the route changes.
  ui = setup(null, false, {
    url: `https://postcards.example/#postcards/${uuid}`,
    fetch: async (url) => response(
      url === "/api/version" ? { version: "0.1.0" }
        : url === `/api/postcards/by-uuid/${uuid}` ? postcard : []),
  });
  await flush();
  assert.equal(ui.get("view-detail").hidden, false);
  assert.equal(ui.get("app-version").textContent, "Version 0.1.0");
  await ui.get("detail-back").emit("click");
  await flush();
  assert.equal(ui.get("view-browse").hidden, false);
  assert.equal(ui.get("app-version").textContent, "Version 0.1.0");

  // index.html keeps the footer outside every <section class="view">, so no
  // view switch can hide it.
  const html = fs.readFileSync(path.join(__dirname, "../app/static/index.html"), "utf8");
  const footer = html.match(/<footer>[\s\S]*?<\/footer>/);
  assert.ok(footer, "index.html must contain a footer element");
  assert.ok(footer[0].includes('id="app-version"'));
  assert.ok(html.indexOf("</main>") < html.indexOf("<footer>"),
    "the footer must live outside <main> with the SPA views");

  console.log("Footer runtime checks passed.");
}

runTests().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
