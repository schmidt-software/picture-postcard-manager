"use strict";

const assert = require("node:assert/strict");
const { setup } = require("./i18n_runtime");

async function runTests() {
  const { run, context, get, postcardForm } = setup();
  for (const path of ["", null, "https://external.invalid/image.png",
    "file:///private/image.png", "javascript:alert(1)", "data:image/png;base64,AA==",
    "http://["]) {
    context.imagePath = path;
    const cell = run('imagePreview(imagePath, "frontImage")');
    assert.equal(cell.children.length, 1);
    assert.equal(cell.children[0].hidden, false);
  }
  const cell = run('imagePreview("/images/front.png", "frontImage")');
  const [fallback, image] = cell.children;
  assert.equal(image.src, "http://127.0.0.1:8000/images/front.png");
  assert.equal(image.alt, "Front image");
  assert.equal(image.loading, "lazy");
  assert.equal(image.width, 96);
  assert.equal(image.height, 72);
  assert.equal(image.hidden, true);
  await image.emit("load");
  assert.equal(image.hidden, false);
  assert.equal(fallback.hidden, true);
  await image.emit("error");
  assert.equal(image.hidden, true);
  assert.equal(fallback.hidden, false);
  assert.equal(fallback.textContent, "Image unavailable");
  const originalQuery = context.document.querySelectorAll;
  context.document.querySelectorAll = (selector) => {
    const staticElements = originalQuery(selector);
    if (selector === "[data-i18n]") return [...staticElements, fallback];
    if (selector === "[data-i18n-alt]") return [...staticElements, image];
    return staticElements;
  };
  run('applyLanguage("de")');
  assert.equal(image.alt, "Vorderseite");
  assert.equal(fallback.textContent, "Bild nicht verfügbar");
  assert.equal(image.hidden, true);
  run('applyLanguage("en")');

  context.postcard = {
    id: 8, front_image_path: "/images/front.png", back_image_path: "",
    place: "Place <script>", region: "Preserved region", year: "1910",
    description: "Preserved description", updated_at: "2026-10-04",
  };
  context.fetch = async () => ({ ok: true, status: 200, json: async () => [context.postcard] });
  await run("loadList()");
  const row = get("postcard-list").children[0];
  const values = row.children.map((child) => child.textContent);
  assert.equal(row.children.length, 7);
  assert.equal(values[0], 8);
  assert.equal(values[3], "Place <script>");
  assert.equal(values[4], "1910");
  assert.equal(values[6], "2026-10-04");
  assert.ok(!values.includes("Preserved region"));
  assert.ok(!values.includes("Preserved description"));
  assert.ok(!values.includes("/images/front.png"));
  await row.emit("click");
  assert.equal(postcardForm.elements.front_image_path.value, "/images/front.png");
  assert.equal(postcardForm.elements.region.value, "Preserved region");
  assert.equal(postcardForm.elements.description.value, "Preserved description");
  assert.equal(get("form-title").textContent, "Edit postcard #8");
  console.log("Thumbnail runtime checks passed.");
}

runTests().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
