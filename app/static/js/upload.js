// Image pickers of the entry form: local previews and deferred uploads.
//
// Selecting a file only renders a local object-URL preview; nothing is
// uploaded until the form is submitted (commitSelections). This avoids
// orphaned uploads for abandoned forms. A selection that was uploaded by a
// failed save keeps its stored path, so retrying the save never uploads the
// same file twice.

import { $ } from "./dom.js";
import { api } from "./api.js";
import { translate, formatApiError, registerRenderer } from "./i18n.js";
import { setValidation } from "./feedback.js";
import { sameOriginImageUrl } from "./preview.js";

export const MAX_IMAGE_BYTES = 20 * 1024 * 1024;
export const IMAGE_TYPES = ["image/png", "image/jpeg", "image/gif", "image/webp"];

// Per-side picker state. `selection` is the locally chosen file with its
// preview object URL and, after a save workflow uploaded it, the stored path.
// `broken` marks a preview image that failed to load (fallback text instead).
const sides = [
  { field: "front_image_path", prefix: "front" },
  { field: "back_image_path", prefix: "back" },
].map((side) => ({ ...side, selection: null, status: null, broken: false }));

// Bumped by resetImagePickers(); a save workflow awaiting an upload aborts
// when its epoch is no longer current (form switched, reset or cancelled).
let epoch = 0;
// True for the whole submit transaction (validation, uploads, postcard save);
// see beginSubmit()/endSubmit(). Guards against double submits and picker
// interactions in handler state, not only via disabled DOM controls.
let submitting = false;
let submitEpoch = -1;

const hiddenInput = (side) => $("#postcard-form").elements[side.field];

export function hasPendingUploads() {
  return submitting;
}

function renderStatus(side) {
  const el = $(`#${side.prefix}-image-status`);
  const status = side.status;
  el.className = status?.error ? "upload-error" : "";
  if (!status) el.textContent = "";
  else if (status.raw !== undefined) {
    el.textContent = translate("imageUploadFailed", { detail: formatApiError(status.raw) });
  } else el.textContent = translate(status.key);
}

// Renders one picker from its selection and hidden path value. The stored
// path itself is never displayed: a non-previewable stored image (e.g. a
// legacy path on another origin) shows the localized fallback text instead.
function render(side) {
  const value = hiddenInput(side).value;
  const hasImage = Boolean(side.selection) || Boolean(value.trim());
  const url = side.selection ? null : sameOriginImageUrl(value);
  const src = side.selection ? side.selection.objectUrl : url?.href ?? "";
  const preview = $(`#${side.prefix}-image-preview`);
  if (src && preview.src !== src) {
    side.broken = false;
    preview.src = src;
  }
  const showPreview = Boolean(src) && !side.broken;
  preview.hidden = !showPreview;
  $(`#${side.prefix}-image-placeholder`).hidden = hasImage;
  $(`#${side.prefix}-image-unavailable`).hidden = !hasImage || showPreview;
  $(`#${side.prefix}-image-clear`).hidden = !hasImage;
  renderStatus(side);
}

function setBusy(flag) {
  submitting = flag;
  for (const side of sides) {
    $(`#${side.prefix}-image-control`).disabled = flag;
    $(`#${side.prefix}-image-clear`).disabled = flag;
  }
  $("#save").disabled = flag;
  $("#postcard-form").setAttribute("aria-busy", String(flag));
}

// Marks the start of a submit transaction. Returns false when one is already
// running (double submit), making the second submit a no-op in the caller.
export function beginSubmit() {
  if (submitting) return false;
  submitEpoch = epoch;
  setBusy(true);
  return true;
}

// Ends the transaction and restores the controls — unless the form was
// switched, reset or cancelled meanwhile (epoch changed): then
// resetImagePickers() already restored the state for the next form and a late
// endSubmit() must not touch it.
export function endSubmit() {
  if (epoch === submitEpoch) setBusy(false);
}

// Token for tying async completions to the originating form session: capture
// it at submit start and bail out of all UI side effects when it is stale.
export function formEpoch() {
  return epoch;
}

function onFileChosen(side) {
  const input = $(`#${side.prefix}-image-file`);
  const file = input.files[0];
  // Clearing the input lets the same file fire another change event later.
  input.value = "";
  if (!file || submitting) return;
  let errorKey = null;
  if (!file.size) errorKey = "errorImageEmpty";
  else if (file.size > MAX_IMAGE_BYTES) errorKey = "errorImageTooLarge";
  else if (!IMAGE_TYPES.includes(file.type)) errorKey = "errorUnsupportedImageType";
  if (errorKey) {
    // A rejected file keeps the previous, still useful selection or stored image.
    side.status = { key: errorKey, error: true };
    return render(side);
  }
  if (side.selection) URL.revokeObjectURL(side.selection.objectUrl);
  side.selection = { file, objectUrl: URL.createObjectURL(file), uploadedPath: null };
  side.status = { key: "imageSelected" };
  if (side.field === "front_image_path") {
    setValidation("front-image-error", $("#front-image-control"), "requiredFrontImage", false);
  }
  render(side);
}

// Clears the selection (revoking its preview) and the hidden path value. A
// stored image is only dissociated when the form is saved afterwards; the
// stored file itself is never deleted here.
function clearSide(side) {
  if (submitting) return;
  if (side.selection) {
    URL.revokeObjectURL(side.selection.objectUrl);
    side.selection = null;
  }
  hiddenInput(side).value = "";
  $(`#${side.prefix}-image-file`).value = "";
  side.status = { key: "imageRemoved" };
  side.broken = false;
  if (side.field === "front_image_path") {
    setValidation("front-image-error", $("#front-image-control"), "requiredFrontImage", false);
  }
  render(side);
  // The clear button just disappeared; keep focus on the picker control.
  $(`#${side.prefix}-image-control`).focus();
}

export function validateFrontImage() {
  const side = sides[0];
  const missing = !side.selection && !hiddenInput(side).value.trim();
  return setValidation(
    "front-image-error", $("#front-image-control"), "requiredFrontImage", missing);
}

// Uploads the pending selections and writes the returned stored paths into
// the hidden fields. Returns false when an upload failed or the form was
// switched meanwhile; the selection and its preview stay intact for a retry.
// Runs inside the submit transaction: beginSubmit() already disabled the
// controls and endSubmit() restores them after the save settles.
export async function commitSelections() {
  const current = epoch;
  for (const side of sides) {
    if (!side.selection || side.selection.uploadedPath) continue;
    side.status = { key: "imageUploading" };
    renderStatus(side);
    const file = side.selection.file;
    let result;
    try {
      result = await api("/api/images", {
        method: "POST", headers: { "Content-Type": file.type }, body: file,
      });
      if (typeof result?.path !== "string" || !result.path) throw new Error("");
    } catch (error) {
      if (epoch !== current) return false;
      side.status = { raw: error?.message || "", error: true };
      renderStatus(side);
      return false;
    }
    if (epoch !== current) return false;
    side.selection.uploadedPath = result.path;
    side.status = { key: "imageUploaded" };
    renderStatus(side);
  }
  for (const side of sides) {
    if (side.selection) hiddenInput(side).value = side.selection.uploadedPath;
  }
  return true;
}

// Drops all selections, revokes their object URLs and re-enables the form.
// Called when the form opens and whenever the edit view is left (reset,
// cancel, navigation, successful save).
export function resetImagePickers() {
  epoch += 1;
  for (const side of sides) {
    if (side.selection) URL.revokeObjectURL(side.selection.objectUrl);
    side.selection = null;
    side.status = null;
    side.broken = false;
    $(`#${side.prefix}-image-file`).value = "";
    // Discard the path state too; openForm refills it for the next form.
    hiddenInput(side).value = "";
  }
  setBusy(false);
  syncImagePickers();
}

// Re-renders both pickers from the hidden path values, e.g. after openForm
// filled in an existing postcard.
export function syncImagePickers() {
  for (const side of sides) render(side);
}

export function initImagePickers() {
  for (const side of sides) {
    $(`#${side.prefix}-image-control`).addEventListener("click", () =>
      $(`#${side.prefix}-image-file`).click());
    $(`#${side.prefix}-image-file`).addEventListener("change", () => onFileChosen(side));
    $(`#${side.prefix}-image-clear`).addEventListener("click", () => clearSide(side));
    $(`#${side.prefix}-image-preview`).addEventListener("error", () => {
      side.broken = true;
      render(side);
    });
    $(`#${side.prefix}-image-preview`).addEventListener("load", () => {
      side.broken = false;
    });
  }
}

registerRenderer(() => sides.forEach(renderStatus));
