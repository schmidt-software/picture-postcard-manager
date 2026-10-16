// Postcard detail page and share links.

import { $ } from "./dom.js";
import { api } from "./api.js";
import { translate, registerRenderer } from "./i18n.js";
import { showApiError } from "./feedback.js";
import { imagePreview } from "./preview.js";
import { navigate, showView, currentRouteRequest } from "./routing.js";

let currentDetail = null;
let detailState = "";
let shareState = "";

export function getCurrentDetail() {
  return currentDetail;
}

// Called when a view other than detail/edit takes over (see showView).
export function clearCurrentDetail() {
  currentDetail = null;
}

// Keeps the loaded detail only when the edit form opens the same postcard.
export function dropDetailUnless(uuid) {
  if (currentDetail?.uuid !== uuid) currentDetail = null;
}

export function renderDetail() {
  $("#detail-title").textContent = currentDetail
    ? translate("postcardDetails", { id: currentDetail.id })
    : translate("detailPage");
  $("#detail-status").textContent = detailState ? translate(detailState) : "";
  $("#detail-status").hidden = !detailState;
  $("#detail-content").hidden = !currentDetail;
  $("#detail-edit").hidden = !currentDetail;
  $("#share-status").textContent = shareState ? translate(shareState) : "";
  if (!currentDetail) return;

  const postcard = currentDetail;
  const photos = [imagePreview(postcard.front_image_path, "frontImage", true)];
  if (postcard.back_image_path) {
    photos.push(imagePreview(postcard.back_image_path, "backImage", true));
  }
  $("#detail-photos").replaceChildren(...photos);
  const metadata = [];
  for (const field of ["place", "region", "year", "description", "tags"]) {
    const value = postcard[field];
    if (!value || (Array.isArray(value) && !value.length)) continue;
    const term = document.createElement("dt");
    term.textContent = translate(field);
    const description = document.createElement("dd");
    if (field === "tags") {
      const tags = document.createElement("ul");
      tags.className = "tag-list postcard-tags";
      for (const tag of value) {
        const chip = document.createElement("li");
        chip.className = "tag";
        chip.textContent = tag;
        tags.append(chip);
      }
      description.append(tags);
    } else {
      description.textContent = value;
    }
    metadata.push(term, description);
  }
  $("#detail-metadata").replaceChildren(...metadata);
}

export async function openDetail(id) {
  const request = currentRouteRequest();
  currentDetail = null;
  shareState = "";
  detailState = id ? "detailLoading" : "detailInvalid";
  showView("detail");
  renderDetail();
  $("#detail-title").focus();
  if (!id) return;
  try {
    const postcard = await api(`/api/postcards/by-uuid/${id}`);
    if (request !== currentRouteRequest()) return;
    currentDetail = postcard;
    detailState = "";
    const url = new URL(window.location.href);
    url.hash = `postcards/${postcard.uuid}`;
    $("#share-url").value = url.href;
    renderDetail();
  } catch (error) {
    if (request !== currentRouteRequest()) return;
    detailState = error.message === "postcard not found" ? "detailMissing" : "detailLoadFailed";
    renderDetail();
    if (detailState === "detailLoadFailed") showApiError(error);
  }
}

export function initDetail() {
  $("#detail-back").addEventListener("click", () => navigate("browse"));
  $("#detail-edit").addEventListener("click", () => {
    if (currentDetail) return navigate(`postcards/${currentDetail.uuid}/edit`);
  });
  $("#copy-share-link").addEventListener("click", async () => {
    if (!currentDetail) return;
    const postcard = currentDetail;
    const url = $("#share-url").value;
    try {
      if (!navigator.clipboard?.writeText) throw new Error("Clipboard unavailable");
      await navigator.clipboard.writeText(url);
      if (currentDetail !== postcard) return;
      shareState = "linkCopied";
    } catch {
      if (currentDetail !== postcard) return;
      shareState = "copyLinkFallback";
      $("#share-url").focus();
      $("#share-url").select();
    }
    $("#share-status").textContent = translate(shareState);
  });
}

registerRenderer(renderDetail);
