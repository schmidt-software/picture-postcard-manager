// Entry form: create and edit postcards.

import { $ } from "./dom.js";
import { api } from "./api.js";
import { translate, registerRenderer } from "./i18n.js";
import { showMessage, showApiError, setValidation } from "./feedback.js";
import { getTags, setTags, commitTagInput } from "./tags.js";
import { hasPendingUploads, resetImagePickers, syncImagePickers, commitSelections, validateFrontImage, beginSubmit, endSubmit } from "./upload.js";
import { navigate, leavePostcard, showView, currentRouteRequest } from "./routing.js";
import { getCurrentDetail, dropDetailUnless } from "./detail.js";
import { deletePostcard } from "./overview.js";

// Opens the form with the postcard's current server state, never a list snapshot.
export async function openEdit(uuid) {
  dropDetailUnless(uuid);
  const request = currentRouteRequest();
  showView("edit");
  setFormLoading(true);
  try {
    const postcard = await api(`/api/postcards/by-uuid/${uuid}`);
    if (request !== currentRouteRequest()) return;
    openForm(postcard);
  } catch (error) {
    if (request !== currentRouteRequest()) return;
    showApiError(error);
    // A temporary failure returns to the view the edit was opened from.
    return leavePostcard(error.message !== "postcard not found");
  }
}

export function setFormLoading(loading) {
  $("#edit-status").hidden = !loading;
  $("#form-title").hidden = loading;
  $("#postcard-form").hidden = loading;
}

export function openForm(postcard = null) {
  const form = $("#postcard-form");
  resetImagePickers();
  form.reset();
  setValidation("front-image-error", $("#front-image-control"), "requiredFrontImage", false);
  form.elements.id.value = postcard?.id ?? "";
  for (const [key, value] of Object.entries(postcard || {})) {
    if (key !== "tags" && form.elements[key]) form.elements[key].value = value;
  }
  syncImagePickers();
  setTags(postcard?.tags ?? []);
  $("#form-title").textContent = postcard
    ? translate("editPostcard", { id: postcard.id }) : translate("newPostcard");
  $("#delete").hidden = !postcard;
  showView("edit");
  setFormLoading(false);
}

function renderFormTitle() {
  const id = $("#postcard-form").elements.id.value;
  $("#form-title").textContent = id ? translate("editPostcard", { id }) : translate("newPostcard");
}

export function initForm() {
  $("#postcard-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    // Transaction guard: one submit transaction (validation, uploads, save)
    // at a time. A programmatic second submit is a no-op too, independent of
    // disabled DOM controls.
    if (hasPendingUploads()) {
      showMessage("uploadPending", {}, true);
      return;
    }
    if (!validateFrontImage()) return;
    if (!beginSubmit()) return;
    try {
      commitTagInput();
      // Upload pending selections now; a failure keeps the selection and
      // preview intact so the save can simply be retried.
      if (!await commitSelections()) return;
      const data = Object.fromEntries(new FormData(e.target));
      data.tags = getTags();
      const id = data.id;
      delete data.id;
      try {
        if (id) await api(`/api/postcards/${id}`, { method: "PUT", body: JSON.stringify(data) });
        else await api("/api/postcards", { method: "POST", body: JSON.stringify(data) });
        showMessage("saved");
        navigate("browse", { replace: true });
      } catch (err) {
        showApiError(err);
      }
    } finally {
      // Restores the controls unless navigation/reset already took over.
      endSubmit();
    }
  });

  $("#delete").addEventListener("click", () =>
    deletePostcard($("#postcard-form").elements.id.value));

  $("#cancel").addEventListener("click", () => {
    const id = $("#postcard-form").elements.id.value;
    // Step back instead of pushing a new entry, so Back does not reopen the form.
    return leavePostcard(Boolean(id) && String(getCurrentDetail()?.id) === String(id));
  });
}

registerRenderer(renderFormTitle);
