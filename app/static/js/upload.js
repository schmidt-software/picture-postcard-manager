// Image upload controls of the entry form.

import { $ } from "./dom.js";
import { api } from "./api.js";
import { translate, formatApiError, registerRenderer } from "./i18n.js";
import { setValidation } from "./feedback.js";

export const MAX_IMAGE_BYTES = 20 * 1024 * 1024;
export const IMAGE_TYPES = ["image/png", "image/jpeg", "image/gif", "image/webp"];
const imageFields = [
  { field: "front_image_path", prefix: "front" },
  { field: "back_image_path", prefix: "back" },
];
// Maps a path field to the token of its current upload. A completed upload only
// updates its field while its token is still current.
const pendingUploads = new Map();
const imageStatus = new Map();

export function hasPendingUploads() {
  return pendingUploads.size > 0;
}

export function renderImageStatus() {
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

export function resetUploads() {
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

export function initUploads() {
  for (const config of imageFields) {
    $(`#choose-${config.prefix}-image`).addEventListener("click", () =>
      $(`#${config.prefix}-image-file`).click());
    $(`#${config.prefix}-image-file`).addEventListener("change", () => uploadImage(config));
    // Typing a path manually takes precedence over a pending upload.
    $("#postcard-form").elements[config.field].addEventListener("input", () =>
      abandonUpload(config.field));
  }
}

registerRenderer(renderImageStatus);
