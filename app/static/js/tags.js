// Tag editor for the entry form.

import { $ } from "./dom.js";
import { translate, registerRenderer } from "./i18n.js";

let currentTags = [];

export function getTags() {
  return [...currentTags];
}

export function setTags(tags) {
  currentTags = [...tags];
  $("#tag-input").value = "";
  renderTagEditor();
}

export function renderTagEditor() {
  $("#tag-list").replaceChildren(...currentTags.map((tag) => {
    const li = document.createElement("li");
    li.className = "tag";
    const text = document.createElement("span");
    text.textContent = tag;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "×";
    remove.setAttribute("aria-label", translate("removeTag", { tag }));
    remove.addEventListener("click", () => {
      currentTags = currentTags.filter((t) => t !== tag);
      renderTagEditor();
      $("#tag-input").focus();
    });
    li.append(text, remove);
    return li;
  }));
}

// Adds the pending input as a tag (trimmed, exact duplicates ignored).
export function commitTagInput() {
  const input = $("#tag-input");
  const tag = input.value.trim();
  if (tag && !currentTags.includes(tag)) currentTags = [...currentTags, tag];
  input.value = "";
  renderTagEditor();
}

export function initTags() {
  $("#add-tag").addEventListener("click", () => {
    commitTagInput();
    $("#tag-input").focus();
  });
  $("#tag-input").addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    commitTagInput();
  });
}

registerRenderer(renderTagEditor);
