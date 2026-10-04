"use strict";

const $ = (sel) => document.querySelector(sel);
const translations = window.UI_TRANSLATIONS;
const LANGUAGE_STORAGE_KEY = "picture-postcard-manager-language";
let currentLanguage = "en";
let currentMessage = null;

function translate(key, params = {}) {
  const value = translations[currentLanguage][key] ?? translations.en[key] ?? key;
  return value.replace(/\{(\w+)\}/g, (match, name) => params[name] ?? match);
}

const apiErrorKeys = {
  "request body too large": "errorRequestTooLarge",
  "not found": "errorNotFound",
  "postcard not found": "errorPostcardNotFound",
  "unknown endpoint": "errorUnknownEndpoint",
  "postcard must be an object": "errorPostcardObject",
  "mode must be 'append' or 'replace'": "errorInvalidMode",
  "payload must be an object with a 'postcards' list": "errorInvalidPayload",
  "every postcard must be an object": "errorInvalidPostcard",
  "front_image_path is required and must be a non-empty string": "errorFrontImageRequired",
  "back_image_path must be a string or null": "errorBackImagePathType",
  "place must be a string or null": "errorPlaceType",
  "region must be a string or null": "errorRegionType",
  "year must be a string or null": "errorYearType",
  "description must be a string or null": "errorDescriptionType",
  "tags must be an array of strings": "errorTagsType",
  "tags must not be blank": "errorTagBlank",
  "unsupported import format": "errorUnsupportedImportFormat",
  "id must be a positive SQLite integer (at most 9223372036854775807)": "errorInvalidId",
  "image upload must not be empty": "errorImageEmpty",
  "image is too large (maximum 20 MiB)": "errorImageTooLarge",
  "unsupported image type; use PNG, JPEG, GIF or WebP": "errorUnsupportedImageType",
  "image content is not a valid PNG, JPEG, GIF or WebP file": "errorInvalidImageContent",
  "image could not be stored": "errorImageStorage",
  "image not found": "errorImageNotFound",
};

function formatApiError(raw) {
  if (Object.hasOwn(apiErrorKeys, raw)) return translate(apiErrorKeys[raw]);
  if (raw.startsWith("unknown postcard fields:")) {
    return translate("errorUnknownPostcardFields", {
      fields: raw.slice("unknown postcard fields:".length).trim(),
    });
  }
  if (raw.startsWith("unknown import fields:")) {
    return translate("errorUnknownImportFields", {
      fields: raw.slice("unknown import fields:".length).trim(),
    });
  }
  if (raw.startsWith("unsupported import schema_version:")) {
    return translate("errorUnsupportedImportVersion", {
      version: raw.slice("unsupported import schema_version:".length).trim(),
    });
  }
  const timestamp = raw.match(/^(created_at|updated_at) must be a non-empty string$/);
  if (timestamp) return translate("errorInvalidTimestamp", { field: timestamp[1] });
  const itemError = raw.match(/^postcard (\d+): (.+)$/);
  if (itemError) {
    const detail = itemError[2].startsWith("UNIQUE constraint failed: postcards.id")
      ? translate("errorDuplicateId")
      : formatApiError(itemError[2]);
    return translate("errorImportPostcard", { index: itemError[1], detail });
  }
  if (raw.startsWith("UNIQUE constraint failed: postcards.id")) {
    return translate("errorDuplicateId");
  }
  if (raw.startsWith("invalid JSON:")) {
    return translate("errorInvalidJson", { detail: raw.slice("invalid JSON:".length).trim() });
  }
  // Browser, parser and unknown server errors can be in any language.
  return translate("errorRequestFailed");
}

function renderMessage() {
  if (!currentMessage) return;
  const { key, params, raw, isError } = currentMessage;
  const detail = key ? translate(key, params) : formatApiError(raw);
  $("#message").textContent = isError ? `${translate("errorPrefix")} ${detail}` : detail;
}

function showMessage(key, params = {}, isError = false, raw = "") {
  currentMessage = { key, params, isError, raw };
  const el = $("#message");
  renderMessage();
  el.className = isError ? "error" : "";
  el.hidden = false;
  clearTimeout(showMessage.timer);
  showMessage.timer = setTimeout(() => (el.hidden = true), 4000);
}

function showApiError(error) {
  showMessage(null, {}, true, error?.message || "");
}

function renderValidation() {
  for (const [id, key] of [
    ["front-image-error", "requiredFrontImage"], ["file-error", "requiredFile"],
  ]) {
    const el = $(`#${id}`);
    if (!el.hidden) el.textContent = translate(key);
  }
}

function setValidation(id, control, key, invalid) {
  const el = $(`#${id}`);
  el.hidden = !invalid;
  el.textContent = invalid ? translate(key) : "";
  control.setAttribute("aria-invalid", String(invalid));
  if (invalid) control.focus();
  return !invalid;
}

function renderFileName() {
  $("#file-name").textContent = $("#import-form").elements.file.files[0]?.name ?? translate("noFile");
}

function applyLanguage(language) {
  currentLanguage = Object.hasOwn(translations, language) ? language : "en";
  document.documentElement.lang = currentLanguage;
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    el.textContent = translate(el.dataset.i18n);
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
    el.placeholder = translate(el.dataset.i18nPlaceholder);
  });
  document.querySelectorAll("[data-i18n-aria-label]").forEach((el) => {
    el.setAttribute("aria-label", translate(el.dataset.i18nAriaLabel));
  });
  document.querySelectorAll("[data-i18n-alt]").forEach((el) => {
    el.alt = translate(el.dataset.i18nAlt);
  });
  $("#language-select").value = currentLanguage;
  const id = $("#postcard-form").elements.id.value;
  $("#form-title").textContent = id ? translate("editPostcard", { id }) : translate("newPostcard");
  renderFileName();
  renderValidation();
  renderImageStatus();
  renderTagEditor();
  renderMessage();
  renderConfirmation();
  try {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, currentLanguage);
  } catch {
    // Selection still works for this page when browser storage is unavailable.
  }
}

let currentConfirmation = null;

function renderConfirmation() {
  if (!currentConfirmation) return;
  $("#confirmation-text").textContent = translate(currentConfirmation.key);
  $("#confirm-action").textContent = translate(currentConfirmation.action);
}

function askConfirmation(key, action) {
  const dialog = $("#confirmation");
  currentConfirmation = { key, action };
  renderConfirmation();
  dialog.returnValue = "";
  return new Promise((resolve) => {
    dialog.addEventListener("close", () => {
      currentConfirmation = null;
      resolve(dialog.returnValue === "confirm");
    }, { once: true });
    dialog.showModal();
  });
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...options.headers },
  });
  if (res.status === 204) return null;
  const data = await res.json();
  if (!res.ok) throw new Error(typeof data.error === "string" ? data.error : "");
  return data;
}

function showView(name) {
  if (name !== "edit") resetUploads();
  document.querySelectorAll(".view").forEach((v) => (v.hidden = v.id !== `view-${name}`));
  document.querySelectorAll("nav button").forEach((b) =>
    b.classList.toggle("active", b.dataset.view === name));
  if (name === "browse") loadList();
}

// --- Tags -------------------------------------------------------------------

let currentTags = [];

function renderTagEditor() {
  $("#tag-list").replaceChildren(...currentTags.map((tag) => {
    const li = document.createElement("li");
    li.className = "tag";
    const text = document.createElement("span");
    text.textContent = tag;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "×";
    remove.setAttribute("aria-label", translate("removeTag", { tag }));
    remove.addEventListener("click", () => {
      currentTags = currentTags.filter((t) => t !== tag);
      renderTagEditor();
      $("#tag-input").focus();
    });
    li.append(text, remove);
    return li;
  }));
}

// Adds the pending input as a tag (trimmed, exact duplicates ignored).
function commitTagInput() {
  const input = $("#tag-input");
  const tag = input.value.trim();
  if (tag && !currentTags.includes(tag)) currentTags = [...currentTags, tag];
  input.value = "";
  renderTagEditor();
}

$("#add-tag").addEventListener("click", () => {
  commitTagInput();
  $("#tag-input").focus();
});
$("#tag-input").addEventListener("keydown", (event) => {
  if (event.key !== "Enter") return;
  event.preventDefault();
  commitTagInput();
});

// --- Browse -----------------------------------------------------------------

function imagePreview(imagePath, side) {
  const cell = document.createElement("td");
  const fallback = document.createElement("span");
  fallback.className = "image-fallback";
  fallback.dataset.i18n = imagePath ? "imageUnavailable" : "noImage";
  fallback.textContent = translate(fallback.dataset.i18n);
  cell.append(fallback);
  if (typeof imagePath !== "string" || !imagePath.trim()) return cell;

  let url;
  try {
    url = new URL(imagePath, window.location.href);
  } catch (error) {
    if (error.name !== "TypeError") throw error;
    return cell;
  }
  // Do not contact external hosts or allow active-content URLs from imported data.
  if (url.origin !== new URL(window.location.href).origin
      || !["http:", "https:"].includes(url.protocol)) return cell;

  const image = document.createElement("img");
  image.className = "postcard-thumbnail";
  image.dataset.i18nAlt = side;
  image.alt = translate(side);
  image.loading = "lazy";
  image.width = 96;
  image.height = 72;
  image.addEventListener("load", () => {
    image.hidden = false;
    image.style.visibility = "visible";
    fallback.hidden = true;
  });
  image.addEventListener("error", () => {
    image.hidden = true;
    fallback.hidden = false;
  });
  cell.append(image);
  image.src = url.href;
  return cell;
}

async function loadList() {
  try {
    const q = $("#search").value.trim();
    const items = await api(`/api/postcards${q ? `?q=${encodeURIComponent(q)}` : ""}`);
    const tbody = $("#postcard-list");
    tbody.replaceChildren(...items.map((p) => {
      const tr = document.createElement("tr");
      const idCell = document.createElement("td");
      idCell.textContent = p.id;
      tr.append(idCell);
      tr.append(imagePreview(p.front_image_path, "frontImage"),
        imagePreview(p.back_image_path, "backImage"));
      for (const field of ["place", "year"]) {
        const td = document.createElement("td");
        td.className = "postcard-value";
        td.textContent = p[field] ?? "";
        tr.append(td);
      }
      const tagsCell = document.createElement("td");
      const tagList = document.createElement("ul");
      tagList.className = "tag-list postcard-tags";
      tagList.append(...(p.tags ?? []).map((tag) => {
        const li = document.createElement("li");
        li.className = "tag";
        li.textContent = tag;
        return li;
      }));
      tagsCell.append(tagList);
      tr.append(tagsCell);
      const updatedCell = document.createElement("td");
      updatedCell.textContent = p.updated_at;
      tr.append(updatedCell);
      tr.addEventListener("click", () => openForm(p));
      return tr;
    }));
    $("#empty-hint").hidden = items.length > 0;
  } catch (err) {
    showApiError(err);
  }
}

// --- Entry form -------------------------------------------------------------

function openForm(postcard = null) {
  const form = $("#postcard-form");
  resetUploads();
  form.reset();
  setValidation("front-image-error", form.elements.front_image_path, "requiredFrontImage", false);
  form.elements.id.value = postcard?.id ?? "";
  for (const [key, value] of Object.entries(postcard || {})) {
    if (key !== "tags" && form.elements[key]) form.elements[key].value = value;
  }
  currentTags = [...(postcard?.tags ?? [])];
  $("#tag-input").value = "";
  renderTagEditor();
  $("#form-title").textContent = postcard
    ? translate("editPostcard", { id: postcard.id }) : translate("newPostcard");
  $("#delete").hidden = !postcard;
  showView("edit");
}

$("#postcard-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (pendingUploads.size) {
    showMessage("uploadPending", {}, true);
    return;
  }
  const frontImagePath = e.target.elements.front_image_path;
  if (!setValidation(
    "front-image-error", frontImagePath, "requiredFrontImage", !frontImagePath.value.trim(),
  )) return;
  commitTagInput();
  const data = Object.fromEntries(new FormData(e.target));
  data.tags = currentTags;
  const id = data.id;
  delete data.id;
  try {
    if (id) await api(`/api/postcards/${id}`, { method: "PUT", body: JSON.stringify(data) });
    else await api("/api/postcards", { method: "POST", body: JSON.stringify(data) });
    showMessage("saved");
    showView("browse");
  } catch (err) {
    showApiError(err);
  }
});

$("#delete").addEventListener("click", async () => {
  const id = $("#postcard-form").elements.id.value;
  if (!id || !await askConfirmation("confirmDelete", "delete")) return;
  try {
    await api(`/api/postcards/${id}`, { method: "DELETE" });
    showMessage("deleted");
    showView("browse");
  } catch (err) {
    showApiError(err);
  }
});

$("#cancel").addEventListener("click", () => showView("browse"));
$("#postcard-form").elements.front_image_path.addEventListener("input", (event) => {
  if (event.target.value.trim()) {
    setValidation("front-image-error", event.target, "requiredFrontImage", false);
  }
});

// --- Image uploads ----------------------------------------------------------

const MAX_IMAGE_BYTES = 20 * 1024 * 1024;
const IMAGE_TYPES = ["image/png", "image/jpeg", "image/gif", "image/webp"];
const imageFields = [
  { field: "front_image_path", prefix: "front" },
  { field: "back_image_path", prefix: "back" },
];
// Maps a path field to the token of its current upload. A completed upload only
// updates its field while its token is still current.
const pendingUploads = new Map();
const imageStatus = new Map();

function renderImageStatus() {
  for (const { field, prefix } of imageFields) {
    const el = $(`#${prefix}-image-status`);
    const status = imageStatus.get(field);
    const failed = status?.raw !== undefined;
    el.className = failed ? "upload-error" : "";
    if (!status) el.textContent = "";
    else if (failed) {
      el.textContent = translate("imageUploadFailed", { detail: formatApiError(status.raw) });
    } else el.textContent = translate(status.key);
  }
}

function updateUploadControls() {
  for (const { field, prefix } of imageFields) {
    $(`#choose-${prefix}-image`).disabled = pendingUploads.has(field);
  }
  $("#save").disabled = pendingUploads.size > 0;
  $("#postcard-form").setAttribute("aria-busy", String(pendingUploads.size > 0));
  renderImageStatus();
}

function resetUploads() {
  pendingUploads.clear();
  imageStatus.clear();
  updateUploadControls();
}

function abandonUpload(field) {
  if (!pendingUploads.delete(field)) return;
  imageStatus.delete(field);
  updateUploadControls();
}

async function uploadImage({ field, prefix }) {
  const input = $(`#${prefix}-image-file`);
  const file = input.files[0];
  input.value = "";
  if (!file) return;
  const token = {};
  pendingUploads.set(field, token);
  imageStatus.set(field, { key: "imageUploading" });
  updateUploadControls();
  let path = null;
  let error = "";
  try {
    if (!file.size) throw new Error("image upload must not be empty");
    if (file.size > MAX_IMAGE_BYTES) throw new Error("image is too large (maximum 20 MiB)");
    if (!IMAGE_TYPES.includes(file.type)) {
      throw new Error("unsupported image type; use PNG, JPEG, GIF or WebP");
    }
    const result = await api("/api/images", {
      method: "POST", headers: { "Content-Type": file.type }, body: file,
    });
    if (typeof result?.path !== "string" || !result.path) throw new Error("");
    path = result.path;
  } catch (err) {
    error = err?.message || "";
  }
  if (pendingUploads.get(field) !== token) return;
  pendingUploads.delete(field);
  if (path === null) {
    imageStatus.set(field, { raw: error });
  } else {
    const control = $("#postcard-form").elements[field];
    control.value = path;
    if (field === "front_image_path") {
      setValidation("front-image-error", control, "requiredFrontImage", false);
    }
    imageStatus.set(field, { key: "imageUploaded" });
  }
  updateUploadControls();
}

for (const config of imageFields) {
  $(`#choose-${config.prefix}-image`).addEventListener("click", () =>
    $(`#${config.prefix}-image-file`).click());
  $(`#${config.prefix}-image-file`).addEventListener("change", () => uploadImage(config));
  // Typing a path manually takes precedence over a pending upload.
  $("#postcard-form").elements[config.field].addEventListener("input", () =>
    abandonUpload(config.field));
}

// --- Import -----------------------------------------------------------------

$("#import-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  const file = form.elements.file.files[0];
  if (!setValidation("file-error", $("#choose-file"), "requiredFile", !file)) return;
  const mode = form.elements.mode.value;
  if (mode === "replace" && !await askConfirmation("confirmReplace", "replace")) return;
  let text;
  try {
    text = await file.text();
  } catch {
    showMessage("errorReadFile", {}, true);
    return;
  }
  try {
    const result = await api(`/api/import?mode=${mode}`, { method: "POST", body: text });
    showMessage("imported", { count: result.imported });
    form.reset();
    renderFileName();
  } catch (err) {
    showApiError(err);
  }
});

// --- Init -------------------------------------------------------------------

Object.entries(translations).forEach(([code, resource]) => {
  const option = document.createElement("option");
  option.value = code;
  option.textContent = resource.languageName ?? code;
  $("#language-select").append(option);
});

$("#language-select").addEventListener("change", (event) => applyLanguage(event.target.value));
let savedLanguage = "en";
try {
  savedLanguage = localStorage.getItem(LANGUAGE_STORAGE_KEY);
} catch {
  // English is the default, independently of the browser's language.
}
applyLanguage(savedLanguage);

$("#choose-file").addEventListener("click", () => $("#import-file").click());
$("#import-file").addEventListener("change", () => {
  renderFileName();
  setValidation("file-error", $("#choose-file"), "requiredFile",
    !$("#import-form").elements.file.files.length);
});

document.querySelectorAll("nav button").forEach((b) =>
  b.addEventListener("click", () => (b.id === "nav-new" ? openForm() : showView(b.dataset.view))));

let searchTimer;
$("#search").addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(loadList, 250);
});

loadList();
