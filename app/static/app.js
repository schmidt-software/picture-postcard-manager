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
};

function formatApiError(raw) {
  if (Object.hasOwn(apiErrorKeys, raw)) return translate(apiErrorKeys[raw]);
  if (raw.startsWith("invalid JSON:")) return translate("errorInvalidJson");
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
  for (const [id, key] of [["title-error", "requiredTitle"], ["file-error", "requiredFile"]]) {
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
  $("#language-select").value = currentLanguage;
  const id = $("#postcard-form").elements.id.value;
  $("#form-title").textContent = id ? translate("editPostcard", { id }) : translate("newPostcard");
  renderFileName();
  renderValidation();
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
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (res.status === 204) return null;
  const data = await res.json();
  if (!res.ok) throw new Error(typeof data.error === "string" ? data.error : "");
  return data;
}

function showView(name) {
  document.querySelectorAll(".view").forEach((v) => (v.hidden = v.id !== `view-${name}`));
  document.querySelectorAll("nav button").forEach((b) =>
    b.classList.toggle("active", b.dataset.view === name));
  if (name === "browse") loadList();
}

// --- Browse -----------------------------------------------------------------

async function loadList() {
  try {
    const q = $("#search").value.trim();
    const items = await api(`/api/postcards${q ? `?q=${encodeURIComponent(q)}` : ""}`);
    const tbody = $("#postcard-list");
    tbody.replaceChildren(...items.map((p) => {
      const tr = document.createElement("tr");
      for (const value of [p.id, p.title, p.notes, p.updated_at]) {
        const td = document.createElement("td");
        td.textContent = value;
        tr.append(td);
      }
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
  form.reset();
  setValidation("title-error", form.elements.title, "requiredTitle", false);
  form.elements.id.value = postcard?.id ?? "";
  for (const [key, value] of Object.entries(postcard || {})) {
    if (form.elements[key]) form.elements[key].value = value;
  }
  $("#form-title").textContent = postcard
    ? translate("editPostcard", { id: postcard.id }) : translate("newPostcard");
  $("#delete").hidden = !postcard;
  showView("edit");
}

$("#postcard-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const title = e.target.elements.title;
  if (!setValidation("title-error", title, "requiredTitle", !title.value)) return;
  const data = Object.fromEntries(new FormData(e.target));
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
$("#postcard-form").elements.title.addEventListener("input", (event) => {
  if (event.target.value) {
    setValidation("title-error", event.target, "requiredTitle", false);
  }
});

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
