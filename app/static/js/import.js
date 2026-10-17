// JSON export/import view.

import { $ } from "./dom.js";
import { api } from "./api.js";
import { translate, registerRenderer } from "./i18n.js";
import { showMessage, showApiError, setValidation, askConfirmation } from "./feedback.js";
import { loadFilterOptions } from "./filters.js";

export function renderFileName() {
  $("#file-name").textContent = $("#import-form").elements.file.files[0]?.name ?? translate("noFile");
}

export function initImport() {
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
      // Imported postcards may add or remove tag/filter values. Refresh the
      // shared filter-values cache now so the tag autocomplete (and the
      // dropdowns) are current even when the user opens the form without
      // revisiting the overview first. One shared request; a failed or stale
      // refresh is handled inside loadFilterOptions and never affects the
      // import result shown above.
      await loadFilterOptions();
    } catch (err) {
      showApiError(err);
    }
  });

  $("#choose-file").addEventListener("click", () => $("#import-file").click());
  $("#import-file").addEventListener("change", () => {
    renderFileName();
    setValidation("file-error", $("#choose-file"), "requiredFile",
      !$("#import-form").elements.file.files.length);
  });
}

registerRenderer(renderFileName);
