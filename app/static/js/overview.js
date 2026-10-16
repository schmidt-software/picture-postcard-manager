// Browse view: search, pagination and the postcard overview table.

import { $ } from "./dom.js";
import { api } from "./api.js";
import { translate, registerRenderer } from "./i18n.js";
import { showMessage, showApiError, askConfirmation } from "./feedback.js";
import { imagePreview } from "./preview.js";
import { navigate, leavePostcard, currentRouteRequest } from "./routing.js";
import { currentSort, initSorting } from "./sorting.js";
import { currentFilters, FILTER_KEYS, loadFilterOptions, initFilters } from "./filters.js";

// Overview pagination: number of rows fetched per request, the rows loaded so
// far (also re-rendered after a language change), and whether the last page
// was short (no more rows on the server).
export const PAGE_SIZE = 100;
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
    const params = [`limit=${PAGE_SIZE}`, `offset=${offset}`];
    if (q) params.push(`q=${encodeURIComponent(q)}`);
    if (currentSort.key) {
      params.push(`sort=${currentSort.key}`, `dir=${currentSort.direction}`);
    }
    for (const key of FILTER_KEYS) {
      if (currentFilters[key]) params.push(`${key}=${encodeURIComponent(currentFilters[key])}`);
    }
    const items = await api(`/api/postcards?${params.join("&")}`);
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
    tr.append(idCell);
    tr.append(imagePreview(p.front_image_path, "frontImage"),
      imagePreview(p.back_image_path, "backImage"));
    for (const field of ["place", "year"]) {
      const td = document.createElement("td");
      td.className = "postcard-value";
      td.textContent = p[field] ?? "";
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
    tr.append(tagsCell);
    const updatedCell = document.createElement("td");
    updatedCell.textContent = p.updated_at;
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
  $("#search").addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => loadList(), 250);
  });
  $("#load-more").addEventListener("click", () => loadList(true));
  initSorting(loadList);
  initFilters(loadList);
}

registerRenderer(renderList);
