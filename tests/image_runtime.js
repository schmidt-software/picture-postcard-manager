"use strict";

// Runtime checks for the form image pickers (issue #45): local previews via
// object URLs, deferred uploads during save, clearing, revocation and
// localization. Uses the shared minimal DOM harness from i18n_runtime.js.
const assert = require("node:assert/strict");
const { setup } = require("./i18n_runtime");

const flush = () => new Promise(setImmediate);
const ok = (body, status = 201) => ({ ok: true, status, json: async () => body });
const fail = (status, error) => ({ ok: false, status, json: async () => ({ error }) });
const png = (name = "card.png", size = 100, type = "image/png") => ({ name, size, type });

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((done, failed) => { resolve = done; reject = failed; });
  return { promise, resolve, reject };
}

// Tracks object URLs so revocation on replace/clear/reset/success is testable.
function trackObjectUrls(ui) {
  const created = [];
  const revoked = [];
  let counter = 0;
  ui.context.URL = class extends URL {
    static createObjectURL(file) {
      const url = `blob:mock-${(counter += 1)}`;
      created.push({ url, file });
      return url;
    }
    static revokeObjectURL(url) { revoked.push(url); }
  };
  return { created, revoked };
}

function pickerSetup({ holdSaves = false } = {}) {
  const uploads = [];
  const saves = [];
  const ui = setup(null, false, {
    fetch(url, options) {
      if (url === "/api/images") {
        const upload = { options, ...deferred() };
        uploads.push(upload);
        return upload.promise;
      }
      if (url.startsWith("/api/postcards") && ["POST", "PUT"].includes(options?.method)) {
        if (holdSaves) {
          const save = { url, options, ...deferred() };
          saves.push(save);
          return save.promise;
        }
        saves.push({ url, options });
        return ok(JSON.parse(options.body), options.method === "POST" ? 201 : 200);
      }
      return ok([], 200);
    },
  });
  const urls = trackObjectUrls(ui);
  return { ...ui, uploads, saves, ...urls };
}

async function choose(ui, side, file) {
  ui.get(`${side}-image-file`).files = [file];
  await ui.get(`${side}-image-file`).emit("change");
  await flush();
}

const visibleText = (ui) =>
  ui.all.map((el) => el.textContent).filter(Boolean).join("\n");

async function testEmptySelectReplaceClearReselect() {
  const ui = pickerSetup();
  const { get, created, revoked } = ui;
  await flush();
  ui.run("openForm()");

  for (const side of ["front", "back"]) {
    // Empty state: accessible placeholder, no preview, no trash button.
    const control = get(`${side}-image-control`);
    assert.equal(control.tag, "button");
    assert.equal(control.type, "button");
    assert.ok(control.attributes["aria-label"]);
    assert.ok(control.attributes["aria-describedby"].includes(`${side}-image-status`));
    assert.equal(get(`${side}-image-placeholder`).hidden, false);
    assert.equal(get(`${side}-image-placeholder`).textContent,
      "No image selected. Opens the file picker.");
    assert.equal(get(`${side}-image-preview`).hidden, true);
    assert.equal(get(`${side}-image-clear`).hidden, true);
    const input = get(`${side}-image-file`);
    assert.equal(input.hidden, true);
    assert.equal(input.type, "file");
    assert.equal(input.accept, "image/png,image/jpeg,image/gif,image/webp");
    // No visible/editable path field: the path lives in a hidden input.
    assert.equal(ui.postcardForm.elements[`${side}_image_path`].type, "hidden");
    // Clicking the control opens the native picker (button semantics give
    // Enter/Space and touch activation for free).
    await control.emit("click");
    assert.equal(input.clicked, true);
  }

  // Selecting a file shows a local object-URL preview; nothing is uploaded.
  const file = png();
  await choose(ui, "front", file);
  assert.equal(created.length, 1);
  assert.equal(created[0].file, file);
  assert.equal(get("front-image-preview").src, "blob:mock-1");
  assert.equal(get("front-image-preview").hidden, false);
  assert.equal(get("front-image-placeholder").hidden, true);
  assert.equal(get("front-image-clear").hidden, false);
  assert.equal(get("front-image-status").textContent, "Image selected.");
  assert.equal(ui.uploads.length, 0, "selection must not upload");
  // The file input is cleared so the same file can fire change again.
  assert.equal(get("front-image-file").value, "");

  // Replacing the selection revokes the previous object URL.
  await choose(ui, "front", png("other.png"));
  assert.deepEqual(revoked, ["blob:mock-1"]);
  assert.equal(get("front-image-preview").src, "blob:mock-2");

  // The trash button clears selection, preview, input and returns focus.
  await get("front-image-clear").emit("click");
  assert.deepEqual(revoked, ["blob:mock-1", "blob:mock-2"]);
  assert.equal(get("front-image-preview").hidden, true);
  assert.equal(get("front-image-placeholder").hidden, false);
  assert.equal(get("front-image-clear").hidden, true);
  assert.equal(get("front-image-file").value, "");
  assert.equal(ui.postcardForm.elements.front_image_path.value, "");
  assert.equal(get("front-image-status").textContent, "Image removed.");
  assert.equal(get("front-image-control").focused, true);

  // The same file can be selected again after clearing.
  await choose(ui, "front", file);
  assert.equal(get("front-image-preview").src, "blob:mock-3");
  assert.equal(get("front-image-clear").hidden, false);

  // Cancelling the native picker changes nothing.
  get("back-image-file").files = [];
  await get("back-image-file").emit("change");
  assert.equal(get("back-image-placeholder").hidden, false);

  // Rejected files keep the current selection and show a localized reason.
  for (const [bad, message] of [
    [png("huge.png", 20 * 1024 * 1024 + 1), "The image is too large. The maximum size is 20 MiB."],
    [png("x.svg", 10, "image/svg+xml"),
      "This image type is not supported. Please choose a PNG, JPEG, GIF or WebP file."],
    [png("empty.png", 0), "The selected image file is empty."],
  ]) {
    await choose(ui, "front", bad);
    assert.equal(get("front-image-preview").src, "blob:mock-3", "selection must be kept");
    assert.equal(get("front-image-status").textContent, message);
    assert.equal(get("front-image-status").className, "upload-error");
  }
  assert.equal(created.length, 3);
  assert.equal(ui.uploads.length, 0);
}

async function testValidationAndSubmission() {
  const ui = pickerSetup();
  const { get, saves, uploads, revoked } = ui;
  await flush();
  ui.run("openForm()");

  // Front image is required: submitting empty shows the localized error.
  await ui.postcardForm.emit("submit");
  assert.equal(saves.length, 0);
  assert.equal(get("front-image-error").hidden, false);
  assert.equal(get("front-image-error").textContent, "Please choose a front image.");
  assert.equal(get("front-image-control").focused, true);
  ui.run('applyLanguage("de")');
  assert.equal(get("front-image-error").textContent,
    "Bitte ein Bild für die Vorderseite auswählen.");
  ui.run('applyLanguage("en")');

  // Selecting a front image clears the validation state.
  await choose(ui, "front", png("front.png"));
  assert.equal(get("front-image-error").hidden, true);
  await choose(ui, "back", png("back.webp", 10, "image/webp"));

  // Submitting uploads front then back, then saves the returned paths.
  const submit = ui.postcardForm.emit("submit");
  await flush();
  assert.equal(uploads.length, 1);
  assert.equal(uploads[0].options.headers["Content-Type"], "image/png");
  assert.equal(uploads[0].options.body.name, "front.png");
  assert.equal(get("save").disabled, true);
  assert.equal(get("front-image-control").disabled, true);
  assert.equal(get("front-image-clear").disabled, true);
  assert.equal(ui.postcardForm.attributes["aria-busy"], "true");
  assert.equal(get("front-image-status").textContent, "Uploading image…");

  // A second submit while uploading is refused.
  const requestCount = ui.requests.length;
  await ui.postcardForm.emit("submit");
  assert.equal(ui.requests.length, requestCount);
  assert.equal(get("message").textContent,
    "Error: Please wait until the image upload has finished.");

  const frontPath = "/images/" + "a".repeat(32) + ".png";
  const backPath = "/images/" + "b".repeat(32) + ".webp";
  uploads[0].resolve(ok({ path: frontPath }));
  await flush();
  assert.equal(uploads.length, 2);
  assert.equal(uploads[1].options.headers["Content-Type"], "image/webp");
  uploads[1].resolve(ok({ path: backPath }));
  await submit;
  await flush();
  assert.equal(saves.length, 1);
  assert.equal(saves[0].options.method, "POST");
  const body = JSON.parse(saves[0].options.body);
  assert.equal(body.front_image_path, frontPath);
  assert.equal(body.back_image_path, backPath);
  assert.equal(ui.postcardForm.attributes["aria-busy"], "false");
  // Success leaves the form; both preview URLs were revoked.
  assert.ok(revoked.includes("blob:mock-1"));
  assert.ok(revoked.includes("blob:mock-2"));
  assert.equal(ui.context.window.location.hash, "#browse");
}

async function testUploadFailureKeepsSelection() {
  const ui = pickerSetup();
  const { get, saves, uploads, revoked } = ui;
  await flush();
  ui.run("openForm()");
  await choose(ui, "front", png("front.png"));
  await choose(ui, "back", png("back.png"));

  // The front upload succeeds but the back upload fails: the save is aborted,
  // both selections and previews stay, and the error is localized.
  let submit = ui.postcardForm.emit("submit");
  await flush();
  uploads[0].resolve(ok({ path: "/images/" + "a".repeat(32) + ".png" }));
  await flush();
  uploads[1].resolve(fail(500, "image could not be stored"));
  await submit;
  assert.equal(saves.length, 0);
  assert.equal(get("front-image-preview").src, "blob:mock-1");
  assert.equal(get("back-image-preview").src, "blob:mock-2");
  assert.deepEqual(revoked, []);
  assert.equal(get("back-image-status").textContent,
    "Image upload failed: The server could not store the image. "
    + "Please try again or contact the administrator. The selected image was kept.");
  assert.equal(get("back-image-status").className, "upload-error");
  assert.equal(get("save").disabled, false);
  ui.run('applyLanguage("de")');
  assert.equal(get("back-image-status").textContent,
    "Hochladen fehlgeschlagen: Der Server konnte das Bild nicht speichern. "
    + "Bitte erneut versuchen oder den Administrator kontaktieren. "
    + "Das ausgewählte Bild wurde beibehalten.");
  ui.run('applyLanguage("en")');

  // Retrying only uploads the still-missing back image (no duplicate upload).
  submit = ui.postcardForm.emit("submit");
  await flush();
  assert.equal(uploads.length, 3);
  assert.equal(uploads[2].options.body.name, "back.png");
  uploads[2].resolve(ok({ path: "/images/" + "b".repeat(32) + ".png" }));
  await submit;
  await flush();
  assert.equal(saves.length, 1);
  const body = JSON.parse(saves[0].options.body);
  assert.equal(body.front_image_path, "/images/" + "a".repeat(32) + ".png");
  assert.equal(body.back_image_path, "/images/" + "b".repeat(32) + ".png");

  // Network errors are localized too.
  ui.run("openForm()");
  await choose(ui, "front", png());
  submit = ui.postcardForm.emit("submit");
  await flush();
  uploads[3].reject(new TypeError("Failed to fetch"));
  await submit;
  assert.equal(get("front-image-status").textContent,
    "Image upload failed: The request failed. Please try again. The selected image was kept.");
  assert.equal(get("front-image-preview").hidden, false);
}

async function testEditMode() {
  const ui = pickerSetup();
  const { get, saves, uploads, revoked } = ui;
  await flush();
  ui.run("openForm({id: 7, front_image_path: '/images/front.png',"
    + " back_image_path: '/images/back.png'})");

  // Stored same-origin images are shown via their server URL; the raw path is
  // never rendered as text anywhere in the UI.
  assert.equal(get("front-image-preview").src, "http://127.0.0.1:8000/images/front.png");
  assert.equal(get("front-image-preview").hidden, false);
  assert.equal(get("front-image-placeholder").hidden, true);
  assert.equal(get("front-image-clear").hidden, false);
  assert.ok(!visibleText(ui).includes("/images/front.png"), "path must not leak as text");

  // Saving without changes keeps both stored paths; nothing is uploaded.
  await ui.postcardForm.emit("submit");
  await flush();
  assert.equal(uploads.length, 0);
  assert.equal(saves.length, 1);
  assert.equal(saves[0].options.method, "PUT");
  assert.equal(JSON.parse(saves[0].options.body).front_image_path, "/images/front.png");
  assert.equal(JSON.parse(saves[0].options.body).back_image_path, "/images/back.png");

  // Replacing the front image previews locally and uploads only on save; the
  // stored file is never deleted by the client (no DELETE request).
  ui.run("openForm({id: 7, front_image_path: '/images/front.png',"
    + " back_image_path: '/images/back.png'})");
  await choose(ui, "front", png("new-front.png"));
  assert.equal(get("front-image-preview").src, "blob:mock-1");
  const submit = ui.postcardForm.emit("submit");
  await flush();
  uploads[0].resolve(ok({ path: "/images/" + "c".repeat(32) + ".png" }));
  await submit;
  await flush();
  assert.equal(saves.length, 2);
  const body = JSON.parse(saves[1].options.body);
  assert.equal(body.front_image_path, "/images/" + "c".repeat(32) + ".png");
  assert.equal(body.back_image_path, "/images/back.png");
  assert.ok(!ui.requests.some((request) => request.options?.method === "DELETE"));

  // Clearing a stored back image empties the association only in form state;
  // it reaches the server when the form is saved.
  ui.run("openForm({id: 7, front_image_path: '/images/front.png',"
    + " back_image_path: '/images/back.png'})");
  await get("back-image-clear").emit("click");
  assert.equal(ui.postcardForm.elements.back_image_path.value, "");
  assert.equal(get("back-image-placeholder").hidden, false);
  await ui.postcardForm.emit("submit");
  await flush();
  assert.equal(JSON.parse(saves[2].options.body).back_image_path, "");

  // Clearing the stored front image re-arms the required validation on save.
  ui.run("openForm({id: 7, front_image_path: '/images/front.png'})");
  await get("front-image-clear").emit("click");
  const count = saves.length;
  await ui.postcardForm.emit("submit");
  assert.equal(saves.length, count);
  assert.equal(get("front-image-error").hidden, false);

  // A stored image that fails to load falls back to localized text.
  ui.run("openForm({id: 7, front_image_path: '/images/front.png'})");
  await get("front-image-preview").emit("error");
  assert.equal(get("front-image-preview").hidden, true);
  assert.equal(get("front-image-unavailable").hidden, false);
  assert.equal(get("front-image-unavailable").textContent, "Image unavailable");
  assert.equal(get("front-image-clear").hidden, false, "broken image can still be cleared");

  // External-origin stored paths are never contacted or rendered.
  ui.run("openForm({id: 7, front_image_path: 'https://evil.example/x.png'})");
  assert.equal(get("front-image-preview").hidden, true);
  assert.equal(get("front-image-unavailable").hidden, false);
  assert.ok(!visibleText(ui).includes("evil.example"));
  assert.deepEqual(revoked, ["blob:mock-1"], "only local object URLs are ever revoked");
}

async function testResetNavigationAndStaleUploads() {
  const ui = pickerSetup();
  const { get, saves, uploads, revoked } = ui;
  await flush();

  // Cancelling the form revokes the selection's object URL.
  ui.run("openForm()");
  await choose(ui, "front", png());
  await get("cancel").emit("click");
  await flush();
  assert.deepEqual(revoked, ["blob:mock-1"]);

  // Re-opening the form drops a previous selection and its object URL.
  ui.run("openForm()");
  await choose(ui, "front", png());
  ui.run("openForm()");
  assert.deepEqual(revoked, ["blob:mock-1", "blob:mock-2"]);
  assert.equal(get("front-image-placeholder").hidden, false);
  assert.equal(get("front-image-clear").hidden, true);

  // Navigating away mid-upload aborts the save: the late upload result never
  // writes into the next form and the object URL was revoked on leave.
  ui.run("openForm()");
  await choose(ui, "front", png());
  const submit = ui.postcardForm.emit("submit");
  await flush();
  assert.equal(get("save").disabled, true);
  ui.run("showView('browse')");
  assert.deepEqual(revoked.at(-1), "blob:mock-3");
  assert.equal(get("save").disabled, false);
  uploads[0].resolve(ok({ path: "/images/" + "a".repeat(32) + ".png" }));
  await submit;
  await flush();
  assert.equal(saves.length, 0, "aborted save must not store the postcard");
  assert.equal(ui.postcardForm.elements.front_image_path.value, "");
}

async function testLocalizationAndAria() {
  const ui = pickerSetup();
  const { get } = ui;
  await flush();
  ui.run("openForm()");

  ui.run('applyLanguage("de")');
  assert.equal(get("front-image-placeholder").textContent,
    "Kein Bild ausgewählt. Öffnet die Dateiauswahl.");
  assert.equal(get("front-image-control").attributes["aria-label"],
    "Bild der Vorderseite auswählen");
  assert.equal(get("back-image-control").attributes["aria-label"],
    "Bild der Rückseite auswählen");
  assert.equal(get("front-image-clear").attributes["aria-label"],
    "Bild der Vorderseite entfernen");
  assert.equal(get("back-image-clear").attributes["aria-label"],
    "Bild der Rückseite entfernen");

  // Status messages re-render on language change.
  await choose(ui, "front", png());
  assert.equal(get("front-image-status").textContent, "Bild ausgewählt.");
  ui.run('applyLanguage("en")');
  assert.equal(get("front-image-status").textContent, "Image selected.");
  await get("front-image-clear").emit("click");
  assert.equal(get("front-image-status").textContent, "Image removed.");
  ui.run('applyLanguage("de")');
  assert.equal(get("front-image-status").textContent, "Bild entfernt.");

  // The trash icon is decorative (not color-only): the accessible name comes
  // from the button's localized aria-label and the icon is hidden from AT.
  const icon = get("front-image-clear").children?.[0]
    ?? ui.all.find((el) => el.class === "icon icon-delete");
  assert.ok(icon, "trash button needs an icon span");
  assert.equal(icon.attributes["aria-hidden"], "true");

  // Status regions are polite live regions.
  for (const side of ["front", "back"]) {
    assert.equal(get(`${side}-image-status`).attributes["aria-live"], "polite");
    assert.equal(get(`${side}-image-status`).attributes.role, "status");
  }
}

// The submit transaction guard (review finding on PR #53): a second submit
// must be a no-op at EVERY point of the transaction — during uploads, in the
// window after uploads settle, and while the postcard save is in flight.
async function testSubmitTransactionGuard() {
  const ui = pickerSetup({ holdSaves: true });
  const { get, saves, uploads } = ui;
  await flush();
  ui.run("openForm()");
  await choose(ui, "front", png("front.png"));

  // First submit: upload starts, transaction busy state is on.
  const submit = ui.postcardForm.emit("submit");
  await flush();
  assert.equal(uploads.length, 1);
  assert.equal(ui.postcardForm.attributes["aria-busy"], "true");

  // Let the upload finish so the save request goes out, then hold the save.
  uploads[0].resolve(ok({ path: "/images/" + "a".repeat(32) + ".png" }));
  await flush();
  assert.equal(saves.length, 1, "save must start after the upload");

  // Programmatic double submit while the save is in flight (disabled DOM
  // controls would not stop this): must be a complete no-op.
  const requestCount = ui.requests.length;
  await ui.postcardForm.emit("submit");
  await ui.postcardForm.emit("submit");
  await flush();
  assert.equal(uploads.length, 1, "each file must be uploaded exactly once");
  assert.equal(saves.length, 1, "in-flight save must block further saves");
  assert.equal(ui.requests.length, requestCount);
  assert.equal(get("message").textContent,
    "Error: Please wait until the image upload has finished.");

  // Busy state covers the whole transaction until the save settles.
  assert.equal(ui.postcardForm.attributes["aria-busy"], "true");
  assert.equal(get("save").disabled, true);
  assert.equal(get("front-image-control").disabled, true);
  assert.equal(get("front-image-clear").disabled, true);

  // Picker interactions are state-guarded too, not only DOM-disabled.
  await choose(ui, "front", png("sneaky.png"));
  assert.equal(get("front-image-preview").src, "blob:mock-1", "selection must not change");
  await get("front-image-clear").emit("click");
  assert.equal(ui.postcardForm.elements.front_image_path.value,
    "/images/" + "a".repeat(32) + ".png", "clear must be a no-op while submitting");

  saves[0].resolve(ok({ id: 1 }));
  await submit;
  await flush();
  assert.equal(saves.length, 1);
  assert.equal(ui.context.window.location.hash, "#browse");

  // After success the guard is released for the next form.
  ui.run("openForm()");
  assert.equal(ui.postcardForm.attributes["aria-busy"], "false");
  assert.equal(get("save").disabled, false);
}

// Save rejection must clear the guard/busy state and allow exactly one
// successful retry without re-uploading the already-uploaded file.
async function testSaveRejectionClearsGuard() {
  const ui = pickerSetup({ holdSaves: true });
  const { get, saves, uploads } = ui;
  await flush();
  ui.run("openForm()");
  await choose(ui, "front", png("front.png"));

  let submit = ui.postcardForm.emit("submit");
  await flush();
  uploads[0].resolve(ok({ path: "/images/" + "a".repeat(32) + ".png" }));
  await flush();
  assert.equal(saves.length, 1);
  saves[0].resolve(fail(500, ""));
  await submit;
  await flush();
  assert.equal(ui.postcardForm.attributes["aria-busy"], "false",
    "busy state must be restored after a failed save");
  assert.equal(get("save").disabled, false);
  assert.equal(get("front-image-control").disabled, false);
  assert.equal(get("front-image-preview").src, "blob:mock-1", "preview survives the failure");

  // Retry: one new save, no duplicate upload of the already-stored image.
  submit = ui.postcardForm.emit("submit");
  await flush();
  assert.equal(uploads.length, 1, "already uploaded file must not be re-uploaded");
  assert.equal(saves.length, 2);
  saves[1].resolve(ok({ id: 1 }));
  await submit;
  await flush();
  assert.equal(JSON.parse(saves[1].options.body).front_image_path,
    "/images/" + "a".repeat(32) + ".png");
  assert.equal(ui.context.window.location.hash, "#browse");
}

// Programmatic double submit without pending images: still exactly one save.
async function testDoubleSubmitWithoutImages() {
  const ui = pickerSetup({ holdSaves: true });
  const { saves, uploads } = ui;
  await flush();
  ui.run("openForm({id: 7, front_image_path: '/images/front.png'})");

  const first = ui.postcardForm.emit("submit");
  const second = ui.postcardForm.emit("submit");
  await flush();
  assert.equal(uploads.length, 0);
  assert.equal(saves.length, 1, "double submit must produce exactly one save");
  assert.equal(ui.postcardForm.attributes["aria-busy"], "true");
  saves[0].resolve(ok({ id: 7 }, 200));
  await Promise.all([first, second]);
  await flush();
  assert.equal(saves.length, 1);
  assert.equal(ui.context.window.location.hash, "#browse");
}

// Stale save completions (second re-review finding on PR #53): a save that
// settles after a newer openForm/reset/navigation finishes server-side but
// must not message, navigate or mutate the newer form session.
async function testStaleSaveCompletionIgnored() {
  const ui = pickerSetup({ holdSaves: true });
  const { get, saves, uploads } = ui;
  await flush();
  ui.run("openForm()");
  await choose(ui, "front", png("old.png"));

  // Old form: upload resolves, the postcard save is held in flight.
  const oldSubmit = ui.postcardForm.emit("submit");
  await flush();
  uploads[0].resolve(ok({ path: "/images/" + "a".repeat(32) + ".png" }));
  await flush();
  assert.equal(saves.length, 1);

  // A fresh form session starts while the old save is still pending.
  ui.run("openForm()");
  const hash = ui.context.window.location.hash;
  get("message").textContent = "";
  get("message").hidden = true;
  await choose(ui, "front", png("new.png"));
  const freshPath = ui.postcardForm.elements.front_image_path.value;
  const freshPreview = get("front-image-preview").src;

  // (1) Old save resolves: no saved message, no navigation, fresh form intact.
  saves[0].resolve(ok({ id: 1 }));
  await oldSubmit;
  await flush();
  assert.equal(get("message").textContent, "", "stale success must not message");
  assert.equal(ui.context.window.location.hash, hash, "stale success must not navigate");
  assert.equal(ui.postcardForm.elements.front_image_path.value, freshPath);
  assert.equal(get("front-image-preview").src, freshPreview);
  assert.equal(get("save").disabled, false, "fresh controls stay enabled");
  assert.equal(get("front-image-control").disabled, false);
  assert.equal(ui.postcardForm.attributes["aria-busy"], "false");

  // The fresh form still submits normally afterwards.
  const freshSubmit = ui.postcardForm.emit("submit");
  await flush();
  assert.equal(uploads.length, 2);
  uploads[1].resolve(ok({ path: "/images/" + "b".repeat(32) + ".png" }));
  await flush();
  assert.equal(saves.length, 2);
  saves[1].resolve(ok({ id: 2 }));
  await freshSubmit;
  await flush();
  assert.equal(get("message").textContent, "Postcard saved.");
  assert.equal(ui.context.window.location.hash, "#browse");
}

// (2) A stale save rejection must not render an error in the fresh form.
async function testStaleSaveRejectionIgnored() {
  const ui = pickerSetup({ holdSaves: true });
  const { get, saves, uploads } = ui;
  await flush();
  ui.run("openForm()");
  await choose(ui, "front", png("old.png"));
  const oldSubmit = ui.postcardForm.emit("submit");
  await flush();
  uploads[0].resolve(ok({ path: "/images/" + "a".repeat(32) + ".png" }));
  await flush();
  assert.equal(saves.length, 1);

  ui.run("openForm()");
  const hash = ui.context.window.location.hash;
  get("message").textContent = "";
  get("message").hidden = true;

  saves[0].resolve(fail(500, ""));
  await oldSubmit;
  await flush();
  assert.equal(get("message").textContent, "", "stale error must not message");
  assert.equal(get("message").hidden, true);
  assert.equal(ui.context.window.location.hash, hash);
  assert.equal(get("save").disabled, false);
  assert.equal(ui.postcardForm.attributes["aria-busy"], "false");
}

// (3) Navigating to another view during the old save: stale resolve and
// reject can neither redirect nor message.
async function testStaleSaveAfterNavigationIgnored() {
  for (const settle of [
    (save) => save.resolve(ok({ id: 1 })),
    (save) => save.resolve(fail(500, "")),
  ]) {
    const ui = pickerSetup({ holdSaves: true });
    const { get, saves, uploads } = ui;
    await flush();
    ui.run("openForm()");
    await choose(ui, "front", png());
    const submit = ui.postcardForm.emit("submit");
    await flush();
    uploads[0].resolve(ok({ path: "/images/" + "a".repeat(32) + ".png" }));
    await flush();
    assert.equal(saves.length, 1);

    ui.run('navigate("data")');
    const hash = ui.context.window.location.hash;
    assert.equal(hash, "#data");
    get("message").textContent = "";
    get("message").hidden = true;

    settle(saves[0]);
    await submit;
    await flush();
    assert.equal(ui.context.window.location.hash, hash, "stale settle must not redirect");
    assert.equal(get("message").textContent, "", "stale settle must not message");
  }
}

async function runTests() {
  await testEmptySelectReplaceClearReselect();
  await testValidationAndSubmission();
  await testUploadFailureKeepsSelection();
  await testEditMode();
  await testResetNavigationAndStaleUploads();
  await testLocalizationAndAria();
  await testSubmitTransactionGuard();
  await testSaveRejectionClearsGuard();
  await testDoubleSubmitWithoutImages();
  // (4) ordinary success and (5) failure+retry on the current epoch are
  // covered by testValidationAndSubmission and testSaveRejectionClearsGuard.
  await testStaleSaveCompletionIgnored();
  await testStaleSaveRejectionIgnored();
  await testStaleSaveAfterNavigationIgnored();
  console.log("Image picker runtime checks passed.");
}

runTests().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
