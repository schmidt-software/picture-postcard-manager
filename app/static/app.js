// Entry point: wires the focused ES modules under js/ together.
//
// Only this module connects routing to the views: initRouting() receives the
// route handlers, so the view modules can import navigate()/showView() from
// routing.js without the import graph ever containing a cycle.

import { initLanguage } from "./js/i18n.js";
import { initFooter } from "./js/footer.js";
import { initTags, resetTagSuggestions } from "./js/tags.js";
import { initYear, resetYearSuggestions } from "./js/year.js";
import { initImagePickers, resetImagePickers } from "./js/upload.js";
import { initDetail, openDetail, clearCurrentDetail } from "./js/detail.js";
import { initForm, openEdit, openForm } from "./js/form.js";
import { initImport } from "./js/import.js";
import { initBulkImport } from "./js/bulk.js";
import { initOverview, loadList, syncOverviewUrl } from "./js/overview.js";
import { loadFilterOptions, syncFiltersFromUrl, renderFilterOptions } from "./js/filters.js";
import { initRouting, route } from "./js/routing.js";

initLanguage();
initTags();
initYear();
initImagePickers();
initDetail();
initForm();
initImport();
initBulkImport();
initOverview();
initRouting({
  openDetail,
  openEdit,
  openForm,
  onBrowse() {
    // Reconcile the tag selection with the URL first (shared URLs, reload,
    // Back/Forward), so the list request below already uses it.
    syncOverviewUrl();
    if (syncFiltersFromUrl()) renderFilterOptions();
    loadFilterOptions();
    return loadList();
  },
  onDetailHidden: clearCurrentDetail,
  // Leaving the edit view resets the image pickers and cancels any pending
  // tag/year-autocomplete popup or timer so nothing outlives the view.
  onEditHidden() {
    resetImagePickers();
    resetTagSuggestions();
    resetYearSuggestions();
  },
});
route();
// After route(): the initial view's data request stays first, the version
// request never delays it, and the footer loads independently of the route.
initFooter();
