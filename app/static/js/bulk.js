// Bulk image import: create postcards from selected image files.

import { $ } from "./dom.js";
import { api } from "./api.js";
import { translate, formatApiError, registerRenderer } from "./i18n.js";
import { MAX_IMAGE_BYTES, IMAGE_TYPES } from "./upload.js";
import { loadFilterOptions } from "./filters.js";
import { loadList } from "./overview.js";

// Groups selected files into postcards: "name-front.jpg" and "name-back.jpg"
// (case-insensitive, also "_front"/"_back") with the same base name form one
// postcard; every other file becomes a postcard with only a front image.
export function groupBulkFiles(files) {
  const pairPattern = /^(.*)[-_](front|back)\.[^.]+$/i;
  const fronts = new Map();
  const backs = new Map();
  const singles = [];
  for (const file of files) {
    const match = file.name.match(pairPattern);
    if (!match) {
      singles.push({ front: file });
      continue;
    }
    const base = match[1].toLowerCase();
    const side = match[2].toLowerCase();
    const map = side === "front" ? fronts : backs;
    // Duplicate sides for one base name are treated as separate postcards.
    if (map.has(base)) singles.push(side === "front" ? { front: file } : { back: file });
    else map.set(base, file);
  }
  const groups = [];
  for (const [base, front] of fronts) {
    const back = backs.get(base);
    if (back) backs.delete(base);
    groups.push({ front, back });
  }
  for (const back of backs.values()) groups.push({ back });
  return [...groups, ...singles];
}

// Client-side validation failures carry a translation key so the per-file
// result list stays localized; server errors keep their raw text and are
// mapped through formatApiError() like everywhere else in the UI.
function bulkValidationError(key) {
  const error = new Error(key);
  error.i18nKey = key;
  return error;
}

function bulkErrorDetail(error) {
  return error?.i18nKey ? translate(error.i18nKey) : formatApiError(error?.message || "");
}

async function uploadBulkImage(file) {
  if (!file.size) throw bulkValidationError("errorImageEmpty");
  if (file.size > MAX_IMAGE_BYTES) throw bulkValidationError("errorImageTooLarge");
  if (!IMAGE_TYPES.includes(file.type)) {
    throw bulkValidationError("errorUnsupportedImageType");
  }
  const result = await api("/api/images", {
    method: "POST", headers: { "Content-Type": file.type }, body: file,
  });
  if (typeof result?.path !== "string" || !result.path) throw new Error("");
  return result.path;
}

export function renderBulkFileCount() {
  const count = $("#bulk-files").files.length;
  $("#bulk-file-count").textContent = count
    ? translate("bulkFilesSelected", { count }) : translate("noFile");
}

let bulkRunning = false;

export async function runBulkImport(files) {
  const results = [];
  let created = 0;
  for (const group of groupBulkFiles(files)) {
    if (!group.front) {
      results.push({ key: "bulkFailed", failed: true, params: {
        name: group.back.name, detail: translate("bulkBackWithoutFront") } });
      continue;
    }
    try {
      const frontPath = await uploadBulkImage(group.front);
      const data = { front_image_path: frontPath };
      let backFailure = null;
      if (group.back) {
        try {
          data.back_image_path = await uploadBulkImage(group.back);
        } catch (err) {
          backFailure = err ?? new Error("");
        }
      }
      const postcard = await api("/api/postcards", {
        method: "POST", body: JSON.stringify(data),
      });
      created += 1;
      if (group.back && !backFailure) {
        results.push({ key: "bulkCreatedPair", params: {
          front: group.front.name, back: group.back.name, id: postcard.id } });
      } else {
        results.push({ key: "bulkCreated", params: { name: group.front.name, id: postcard.id } });
      }
      if (backFailure !== null) {
        results.push({ key: "bulkFailed", failed: true, params: {
          name: group.back.name, detail: bulkErrorDetail(backFailure) } });
      }
    } catch (err) {
      results.push({ key: "bulkFailed", failed: true, params: {
        name: group.front.name, detail: bulkErrorDetail(err) } });
    }
  }
  return { results, created, failed: results.filter((r) => r.failed).length };
}

export function initBulkImport() {
  $("#choose-bulk-files").addEventListener("click", () => $("#bulk-files").click());
  $("#bulk-files").addEventListener("change", () => {
    renderBulkFileCount();
    $("#bulk-error").hidden = true;
  });

  $("#bulk-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    if (bulkRunning) return;
    const files = [...$("#bulk-files").files];
    const errorEl = $("#bulk-error");
    if (!files.length) {
      errorEl.textContent = translate("bulkNoFiles");
      errorEl.hidden = false;
      return;
    }
    errorEl.hidden = true;
    bulkRunning = true;
    $("#bulk-start").disabled = true;
    $("#bulk-summary").hidden = false;
    $("#bulk-summary").textContent = translate("bulkRunning");
    $("#bulk-results").replaceChildren();
    try {
      const { results, created, failed } = await runBulkImport(files);
      $("#bulk-summary").textContent = translate("bulkSummary", { created, failed });
      $("#bulk-results").replaceChildren(...results.map((result) => {
        const li = document.createElement("li");
        li.className = result.failed ? "bulk-failed" : "bulk-created";
        li.textContent = translate(result.key, result.params);
        return li;
      }));
      $("#bulk-files").value = "";
      renderBulkFileCount();
      // Created postcards may introduce new filter values. Returning to the
      // overview reloads the dropdowns on entry (showView), but the user may
      // already have navigated back while the import was still running, so the
      // dropdowns and the list are refreshed here as well. An active selection
      // stays selectable (see renderFilterOptions).
      if (created && !$("#view-browse").hidden) {
        await Promise.all([loadFilterOptions(), loadList()]);
      }
    } finally {
      bulkRunning = false;
      $("#bulk-start").disabled = false;
    }
  });
}

registerRenderer(renderBulkFileCount);
