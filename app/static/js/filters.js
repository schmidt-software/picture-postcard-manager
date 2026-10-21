// Overview filters: filter state, persistence, dropdown values and controls.
//
// The tag filter accepts any number of tags with AND semantics (issue #52).
// Selected tags are rendered as removable chips, new tags are added through a
// native select (keyboard, pointer and touch accessible without custom
// widget code), and the selection is mirrored into the overview URL as
// repeated `tag` parameters so reload, Back/Forward and shared URLs keep it.

import { $ } from "./dom.js";
import { api } from "./api.js";
import { translate, registerRenderer } from "./i18n.js";

const FILTER_STORAGE_KEY = "picture-postcard-manager-filters";
export const FILTER_KEYS = ["year", "tag"];
export let currentFilters = { year: "", tag: [] };
let filterValues = { year: [], tag: [] };
// Incremented per filter-values request; stale responses must not overwrite
// the dropdowns a newer request already rebuilt.
let filterOptionsRequest = 0;
// Modules that reuse the cached values (the tag autocomplete) subscribe here
// instead of issuing their own filter-values requests.
const filterValuesListeners = [];

export function onFilterValuesLoaded(listener) {
  filterValuesListeners.push(listener);
}

// The distinct tags of all existing postcards, as of the last successful
// filter-values load (server-side order; stored spelling preserved).
export function getKnownTags() {
  return [...filterValues.tag];
}

// The distinct years of all existing postcards, as of the last successful
// filter-values load (server-side order; stored spelling preserved). Source
// of the year combobox suggestions in the entry form (issue #65).
export function getKnownYears() {
  return [...filterValues.year];
}

// Canonical tag-selection cleanup: strings only, blank and whitespace-only
// values dropped, exact duplicates removed while the first occurrence keeps
// its position. Non-blank values are preserved verbatim (stored spelling,
// including any surrounding whitespace) - a value that does not match a
// stored tag simply yields an empty result, never an error. The selection
// order is the canonical order everywhere (chips, URL, requests).
function cleanTagSelection(value) {
  const tags = [];
  for (const tag of Array.isArray(value) ? value : []) {
    if (typeof tag === "string" && tag.trim() && !tags.includes(tag)) tags.push(tag);
  }
  return tags;
}

export function loadSavedFilters() {
  try {
    const saved = JSON.parse(localStorage.getItem(FILTER_STORAGE_KEY));
    if (typeof saved?.year === "string") currentFilters.year = saved.year;
    // Legacy single-tag state (a string, pre issue #52) migrates to a
    // one-element selection through the same canonicalization as arrays, so
    // blank or whitespace-only legacy values are dropped; anything invalid
    // falls back to no tags.
    if (typeof saved?.tag === "string") {
      currentFilters.tag = cleanTagSelection([saved.tag]);
    } else if (Array.isArray(saved?.tag)) {
      currentFilters.tag = cleanTagSelection(saved.tag);
    }
  } catch {
    // No filters are applied when browser storage is unavailable or invalid.
  }
}

export function setFilters(filters) {
  currentFilters = { year: typeof filters?.year === "string" ? filters.year : "", tag: cleanTagSelection(filters?.tag) };
  saveFilters();
  renderFilterOptions();
}

export function saveFilters() {
  try {
    localStorage.setItem(FILTER_STORAGE_KEY, JSON.stringify(currentFilters));
  } catch {
    // Filters still work for this page when browser storage is unavailable.
  }
}

// Parses the repeated `tag` parameters of the current URL into a canonical
// selection: order preserved, blanks dropped, duplicates removed. A single
// `tag` parameter (pre-#52 URLs) is simply a one-element list.
export function tagsFromUrl() {
  return cleanTagSelection(
    new URLSearchParams(window.location.search).getAll("tag"));
}

// Writes the current tag selection into the URL as repeated `tag` parameters
// (selection order, no duplicates) without adding a history entry, so the
// overview URL is always shareable and survives reload and Back/Forward.
// URLSearchParams handles all escaping, so hostile or special characters in
// tag values never corrupt the URL.
function writeTagsToUrl() {
  const url = new URL(window.location.href);
  url.searchParams.delete("tag");
  for (const tag of currentFilters.tag) url.searchParams.append("tag", tag);
  if (url.href === window.location.href) return;
  window.history.replaceState(window.history.state, "", url);
}

// Entering the overview makes the URL authoritative for the tag selection:
// the repeated `tag` parameters of the current URL (shared links, reload,
// Back/Forward) are parsed, canonicalized and applied, and a URL without any
// `tag` parameter means no tag filter - the previously active or stored
// selection is cleared and persisted, never re-injected into a bare URL.
// Returns true when the selection changed, so the caller can re-render
// before loading the list.
export function syncFiltersFromUrl() {
  const tags = tagsFromUrl();
  const changed = JSON.stringify(tags) !== JSON.stringify(currentFilters.tag);
  currentFilters.tag = tags;
  if (changed) saveFilters();
  writeTagsToUrl(); // canonicalize duplicates/blanks in the address bar
  return changed;
}

function announceTagFilter(key, params = {}) {
  $("#filter-tag-status").textContent = translate(key, params);
}

// Available choices for the add-select: known tags minus the selected ones,
// in a deterministic locale-aware order with a code-point tiebreaker. The
// stored spelling is always preserved.
function availableTagChoices() {
  const locale = document.documentElement.lang || "en";
  return getKnownTags()
    .filter((tag) => !currentFilters.tag.includes(tag))
    .sort((a, b) => a.localeCompare(b, locale) || (a < b ? -1 : a > b ? 1 : 0));
}

function renderTagChips() {
  $("#filter-tag-list").replaceChildren(...currentFilters.tag.map((tag, index) => {
    const li = document.createElement("li");
    li.className = "tag";
    const text = document.createElement("span");
    text.textContent = tag;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "×";
    remove.setAttribute("aria-label", translate("removeTagFilter", { tag }));
    remove.addEventListener("click", () => removeTagFilter(tag, index));
    li.append(text, remove);
    return li;
  }));
  const clear = $("#filter-tag-clear");
  clear.hidden = currentFilters.tag.length === 0;
}

// Rebuilds the filter controls from the known values. A selected year that no
// postcard currently offers stays selectable; selected tags stay visible as
// chips even when their last use disappeared, so the active filter state is
// never changed silently (the user removes them explicitly).
export function renderFilterOptions() {
  const select = $("#filter-year");
  const values = [...filterValues.year];
  if (currentFilters.year && !values.includes(currentFilters.year)) {
    values.unshift(currentFilters.year);
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
  select.value = currentFilters.year;

  const tagSelect = $("#filter-tag");
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = translate("filterTagAdd");
  tagSelect.replaceChildren(placeholder, ...availableTagChoices().map((tag) => {
    const option = document.createElement("option");
    option.value = tag;
    option.textContent = tag;
    return option;
  }));
  tagSelect.value = "";
  renderTagChips();
  $("#filter-reset").hidden = !currentFilters.year && currentFilters.tag.length === 0;
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
  for (const listener of filterValuesListeners) listener();
}

// Injected by initFilters (the overview's loadList); tag add/remove/clear
// reuse it so every change reloads the first page of the filtered list.
let filtersChanged = () => {};

function applyTagSelection() {
  saveFilters();
  writeTagsToUrl();
  renderFilterOptions();
  filtersChanged();
}

function addTagFilter(tag) {
  if (!tag || currentFilters.tag.includes(tag)) return;
  currentFilters.tag = [...currentFilters.tag, tag];
  applyTagSelection();
  announceTagFilter("tagFilterAdded", { tag });
  // Focus stays on the select so several tags can be added in a row.
  $("#filter-tag").focus();
}

function removeTagFilter(tag, index) {
  currentFilters.tag = currentFilters.tag.filter((t) => t !== tag);
  applyTagSelection();
  announceTagFilter("tagFilterRemoved", { tag });
  // Predictable focus: the chip now at the removed position (or the last
  // one), falling back to the add-select when no chips remain.
  const chips = $("#filter-tag-list").children;
  const next = chips[Math.min(index, chips.length - 1)];
  const button = next?.children?.[1];
  if (button) button.focus();
  else $("#filter-tag").focus();
}

function clearTagFilters() {
  if (currentFilters.tag.length === 0) return;
  currentFilters.tag = [];
  applyTagSelection();
  announceTagFilter("tagFilterCleared");
  $("#filter-tag").focus();
}

// onChange is injected (the overview's loadList) so this module stays a leaf.
// Changing a filter returns to the first page of the newly filtered list.
export function initFilters(onChange) {
  filtersChanged = onChange;
  $("#filter-year").addEventListener("change", (event) => {
    currentFilters.year = event.target.value;
    saveFilters();
    renderFilterOptions();
    onChange();
  });
  $("#filter-tag").addEventListener("change", (event) => {
    addTagFilter(event.target.value);
  });
  $("#filter-tag-clear").addEventListener("click", clearTagFilters);
  $("#filter-reset").addEventListener("click", () => {
    currentFilters = { year: "", tag: [] };
    saveFilters();
    writeTagsToUrl();
    renderFilterOptions();
    onChange();
  });
  loadSavedFilters();
  renderFilterOptions();
}

registerRenderer(renderFilterOptions);
