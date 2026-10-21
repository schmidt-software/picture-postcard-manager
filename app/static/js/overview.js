// Browse view: search, pagination and the postcard overview table.

import { $ } from "./dom.js";
import { api } from "./api.js";
import { translate, registerRenderer } from "./i18n.js";
import { showMessage, showApiError, askConfirmation } from "./feedback.js";
import { imagePreview } from "./preview.js";
import { navigate, leavePostcard, currentRouteRequest } from "./routing.js";
import { currentSort, initSorting, setSort } from "./sorting.js";
import { currentFilters, loadFilterOptions, initFilters, setFilters } from "./filters.js";
import { initSavedViews } from "./saved_views.js";

// Overview pagination: number of rows fetched per request, the rows loaded so
// far (also re-rendered after a language change), and whether the last page
// was short (no more rows on the server).
export const PAGE_SIZE = 100;

export function overviewState() {
  return { q: $("#search").value.trim(), year: currentFilters.year, tag: currentFilters.tag,
    sort: currentSort.key, dir: currentSort.key ? currentSort.direction : "" };
}

export function syncOverviewUrl() {
  const params = new URLSearchParams(window.location.search);
  if (params.has("q")) $("#search").value = params.get("q") || "";
  if (params.has("year")) setFilters({ year: params.get("year") || "", tag: currentFilters.tag });
  if (params.has("sort") || params.has("dir")) {
    setSort({ key: params.get("sort") || "", direction: params.get("dir") || "asc" });
  }
}

export function applyOverviewState(raw) {
  const url = new URL(raw, window.location.href);
  const params = url.searchParams;
  $("#search").value = params.get("q") || "";
  setFilters({ year: params.get("year") || "", tag: params.getAll("tag") });
  setSort({ key: params.get("sort") || "", direction: params.get("dir") || "asc" });
  const next = new URL(window.location.href);
  next.search = url.search;
  window.history.replaceState(window.history.state, "", next);
  return loadList();
}
let currentItems = null;
let listComplete = true;
let listRequest = 0;

// Loads one page of the overview; append=true fetches the page after the rows
// loaded so far, otherwise the list restarts at the first page. Only the
// newest request may update the list, the error display and the load-more
// state: an older, slower response (e.g. for a previous sort order, filter
// set or search term) is dropped on both the success and the error path, so
// it never overwrites or extends the rows of a newer one.
export async function loadList(append = false) {
  const request = ++listRequest;
  try {
    const q = $("#search").value.trim();
    const offset = append && currentItems ? currentItems.length : 0;
    const params = new URLSearchParams();
    params.set("limit", PAGE_SIZE);
    params.set("offset", offset);
    if (q) params.set("q", q);
    if (currentSort.key) {
      params.set("sort", currentSort.key);
      params.set("dir", currentSort.direction);
    }
    if (currentFilters.year) params.set("year", currentFilters.year);
    // Repeated tag parameters, AND semantics (issue #52); URLSearchParams
    // escapes every value, so special characters never corrupt the query.
    for (const tag of currentFilters.tag) params.append("tag", tag);
    const items = await api(`/api/postcards?${params}`);
    if (request !== listRequest) return;
    currentItems = append && currentItems ? currentItems.concat(items) : items;
    listComplete = items.length < PAGE_SIZE;
    renderList();
  } catch (err) {
    if (request !== listRequest) return;
    showApiError(err);
  }
}

// Builds the overview from the last loaded items, also after a language change.
export function renderList() {
  if (!currentItems) return;
  $("#postcard-list").replaceChildren(...currentItems.map((p) => {
    const tr = document.createElement("tr");
    const idCell = document.createElement("td");
    idCell.textContent = p.id;
    idCell.dataset.label = translate("id");
    tr.append(idCell);
    const frontCell = imagePreview(p.front_image_path, "frontImage");
    frontCell.dataset.label = translate("frontImage");
    const backCell = imagePreview(p.back_image_path, "backImage");
    backCell.dataset.label = translate("backImage");
    tr.append(frontCell, backCell);
    for (const field of ["year"]) {
      const td = document.createElement("td");
      td.className = "postcard-value";
      td.textContent = p[field] ?? "";
      td.dataset.label = translate(field);
      tr.append(td);
    }
    const tagsCell = document.createElement("td");
    const tagList = document.createElement("ul");
    tagList.className = "tag-list postcard-tags";
    tagList.append(...(p.tags ?? []).map((tag) => {
      const li = document.createElement("li");
      li.className = "tag";
      li.textContent = tag;
      return li;
    }));
    tagsCell.append(tagList);
    tagsCell.dataset.label = translate("tags");
    tr.append(tagsCell);
    const updatedCell = document.createElement("td");
    updatedCell.textContent = p.updated_at;
    updatedCell.dataset.label = translate("updated");
    tr.append(updatedCell);
    const actionCell = document.createElement("td");
    const actions = document.createElement("div");
    actions.className = "row-actions";
    for (const [key, name, action] of [
      ["editPostcard", "edit", () => navigate(`postcards/${p.uuid}/edit`)],
      ["deletePostcard", "delete", () => deletePostcard(p.id)],
    ]) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `row-${name}`;
      const label = translate(key, { id: p.id });
      button.setAttribute("aria-label", label);
      button.title = label;
      const symbol = document.createElement("span");
      symbol.className = `icon icon-${name}`;
      symbol.setAttribute("aria-hidden", "true");
      button.append(symbol);
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        return action();
      });
      actions.append(button);
    }
    actionCell.append(actions);
    actionCell.dataset.label = translate("rowActions");
    tr.append(actionCell);
    tr.tabIndex = 0;
    tr.setAttribute("aria-label", translate("viewPostcard", { id: p.id }));
    tr.addEventListener("click", () => navigate(`postcards/${p.uuid}`));
    tr.addEventListener("keydown", (event) => {
      if (event.target !== tr) return;
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        navigate(`postcards/${p.uuid}`);
      }
    });
    return tr;
  }));
  $("#empty-hint").hidden = currentItems.length > 0;
  $("#load-more").hidden = listComplete;
}

let deletionPending = false;

// Deletes a postcard from the overview's row actions or the edit form.
export async function deletePostcard(id) {
  if (!id || deletionPending) return;
  deletionPending = true;
  // Decide where to go from the view the deletion started in: the user may open
  // another view while the request is running.
  const fromForm = !$("#view-edit").hidden;
  try {
    if (!await askConfirmation("confirmDelete", "delete")) return;
    const request = currentRouteRequest();
    await api(`/api/postcards/${id}`, { method: "DELETE" });
    showMessage("deleted");
    if (request === currentRouteRequest() && fromForm) await leavePostcard();
    else if (!$("#view-browse").hidden) {
      // The deleted postcard may have carried the last use of a filter value,
      // so the dropdowns are reloaded along with the list. An active selection
      // stays selectable (see renderFilterOptions), showing an empty result.
      await Promise.all([loadFilterOptions(), loadList()]);
    }
  } catch (err) {
    showApiError(err);
  } finally {
    deletionPending = false;
  }
}

export function initOverview() {
  let searchTimer;
  initSavedViews({ getState: overviewState, applyState: applyOverviewState });
  $("#search").addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => loadList(), 250);
  });
  $("#load-more").addEventListener("click", () => loadList(true));
  initSorting(loadList);
  initFilters(loadList);
}

registerRenderer(renderList);
