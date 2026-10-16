// Overview filters: filter state, persistence, dropdown values and controls.

import { $ } from "./dom.js";
import { api } from "./api.js";
import { translate, registerRenderer } from "./i18n.js";

const FILTER_STORAGE_KEY = "picture-postcard-manager-filters";
export const FILTER_KEYS = ["place", "region", "year", "tag"];
export let currentFilters = { place: "", region: "", year: "", tag: "" };
let filterValues = { place: [], region: [], year: [], tag: [] };
// Incremented per filter-values request; stale responses must not overwrite
// the dropdowns a newer request already rebuilt.
let filterOptionsRequest = 0;

export function loadSavedFilters() {
  try {
    const saved = JSON.parse(localStorage.getItem(FILTER_STORAGE_KEY));
    for (const key of FILTER_KEYS) {
      if (typeof saved?.[key] === "string") currentFilters[key] = saved[key];
    }
  } catch {
    // No filters are applied when browser storage is unavailable or invalid.
  }
}

export function saveFilters() {
  try {
    localStorage.setItem(FILTER_STORAGE_KEY, JSON.stringify(currentFilters));
  } catch {
    // Filters still work for this page when browser storage is unavailable.
  }
}

// Rebuilds each filter dropdown from the known values, keeping an active
// selection even when no postcard currently offers it.
export function renderFilterOptions() {
  for (const key of FILTER_KEYS) {
    const select = $(`#filter-${key}`);
    const values = [...filterValues[key]];
    if (currentFilters[key] && !values.includes(currentFilters[key])) {
      values.unshift(currentFilters[key]);
    }
    const all = document.createElement("option");
    all.value = "";
    all.textContent = translate("filterAll");
    select.replaceChildren(all, ...values.map((value) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = value;
      return option;
    }));
    select.value = currentFilters[key];
  }
  $("#filter-reset").hidden = !FILTER_KEYS.some((key) => currentFilters[key]);
}

export async function loadFilterOptions() {
  const request = ++filterOptionsRequest;
  try {
    const values = await api("/api/postcards/filters");
    if (request !== filterOptionsRequest) return;
    for (const key of FILTER_KEYS) {
      if (Array.isArray(values?.[key])) filterValues[key] = values[key];
    }
  } catch {
    if (request !== filterOptionsRequest) return;
    // The dropdowns keep their previous values; filtering still works.
  }
  renderFilterOptions();
}

// onChange is injected (the overview's loadList) so this module stays a leaf.
// Changing a filter returns to the first page of the newly filtered list.
export function initFilters(onChange) {
  for (const key of FILTER_KEYS) {
    $(`#filter-${key}`).addEventListener("change", (event) => {
      currentFilters[key] = event.target.value;
      saveFilters();
      renderFilterOptions();
      onChange();
    });
  }
  $("#filter-reset").addEventListener("click", () => {
    currentFilters = { place: "", region: "", year: "", tag: "" };
    saveFilters();
    renderFilterOptions();
    onChange();
  });
  loadSavedFilters();
  renderFilterOptions();
}

registerRenderer(renderFilterOptions);
