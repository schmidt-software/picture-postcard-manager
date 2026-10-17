// Transient status messages, form validation hints and confirmation dialog.

import { $ } from "./dom.js";
import { translate, formatApiError, registerRenderer } from "./i18n.js";

let currentMessage = null;
let currentConfirmation = null;

export function renderMessage() {
  if (!currentMessage) return;
  const { key, params, raw, isError } = currentMessage;
  const detail = key ? translate(key, params) : formatApiError(raw);
  $("#message").textContent = isError ? `${translate("errorPrefix")} ${detail}` : detail;
}

export function showMessage(key, params = {}, isError = false, raw = "") {
  currentMessage = { key, params, isError, raw };
  const el = $("#message");
  renderMessage();
  el.className = isError ? "error" : "";
  el.hidden = false;
  clearTimeout(showMessage.timer);
  showMessage.timer = setTimeout(() => (el.hidden = true), 4000);
}

export function showApiError(error) {
  showMessage(null, {}, true, error?.message || "");
}

export function renderValidation() {
  for (const [id, key] of [
    ["front-image-error", "requiredFrontImage"], ["year-error", "invalidYear"],
    ["file-error", "requiredFile"],
  ]) {
    const el = $(`#${id}`);
    if (!el.hidden) el.textContent = translate(key);
  }
}

export function setValidation(id, control, key, invalid) {
  const el = $(`#${id}`);
  el.hidden = !invalid;
  el.textContent = invalid ? translate(key) : "";
  control.setAttribute("aria-invalid", String(invalid));
  if (invalid) control.focus();
  return !invalid;
}

export function renderConfirmation() {
  if (!currentConfirmation) return;
  $("#confirmation-text").textContent = translate(currentConfirmation.key);
  $("#confirm-action").textContent = translate(currentConfirmation.action);
}

export function askConfirmation(key, action) {
  const dialog = $("#confirmation");
  if (dialog.open) return Promise.resolve(false);
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

registerRenderer(renderMessage);
registerRenderer(renderValidation);
registerRenderer(renderConfirmation);
