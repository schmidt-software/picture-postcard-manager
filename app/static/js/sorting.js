// Overview sorting: sort key/direction state, persistence and controls.

import { $ } from "./dom.js";
import { translate } from "./i18n.js";

const SORT_STORAGE_KEY = "picture-postcard-manager-sort";
export const SORT_KEYS = ["year", "updated"];
export let currentSort = { key: "", direction: "asc" };

export function loadSavedSort() {
  try {
    const saved = JSON.parse(localStorage.getItem(SORT_STORAGE_KEY));
    if (saved && SORT_KEYS.includes(saved.key)
        && ["asc", "desc"].includes(saved.direction)) {
      currentSort = { key: saved.key, direction: saved.direction };
    }
  } catch {
    // Newest-first is the default when storage is unavailable or invalid.
  }
}

export function setSort(sort) {
  currentSort = {
    key: SORT_KEYS.includes(sort?.key) ? sort.key : "",
    direction: ["asc", "desc"].includes(sort?.direction) ? sort.direction : "asc",
  };
  saveSort();
  renderSortControls();
}

export function saveSort() {
  try {
    localStorage.setItem(SORT_STORAGE_KEY, JSON.stringify(currentSort));
  } catch {
    // Sorting still works for this page when browser storage is unavailable.
  }
}

export function renderSortControls() {
  $("#sort-select").value = currentSort.key;
  const direction = $("#sort-direction");
  direction.hidden = !currentSort.key;
  direction.dataset.i18n = currentSort.direction === "desc" ? "sortDescending" : "sortAscending";
  direction.textContent = translate(direction.dataset.i18n);
  direction.setAttribute("aria-pressed", String(currentSort.direction === "desc"));
}

// onChange is injected (the overview's loadList) so this module stays a leaf.
// Changing the sort key or direction resets the overview to its first page.
export function initSorting(onChange) {
  $("#sort-select").addEventListener("change", (event) => {
    currentSort = { key: event.target.value, direction: "asc" };
    saveSort();
    renderSortControls();
    onChange();
  });
  $("#sort-direction").addEventListener("click", () => {
    if (!currentSort.key) return;
    currentSort = {
      key: currentSort.key,
      direction: currentSort.direction === "asc" ? "desc" : "asc",
    };
    saveSort();
    renderSortControls();
    onChange();
  });
  loadSavedSort();
  renderSortControls();
}
