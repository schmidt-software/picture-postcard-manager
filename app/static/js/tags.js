// Tag editor for the entry form, with autocomplete suggestions built from the
// tags already used by existing postcards (issue #47).
//
// The suggestion source is the cached filter-values response maintained by
// filters.js: no request is sent per keystroke, and every place that reloads
// the filter dropdowns (save, delete, JSON import, bulk import, entering the
// overview) refreshes the suggestions through onFilterValuesLoaded. A failed
// load simply leaves the list empty, so free tag entry keeps working.

import { $ } from "./dom.js";
import { translate, registerRenderer } from "./i18n.js";
import { getKnownTags, onFilterValuesLoaded } from "./filters.js";

let currentTags = [];

// Autocomplete state. `suggestions` holds the rendered matches in order;
// `activeIndex` is the keyboard-active option (-1: none). `composing` guards
// against accepting while an IME composition is still in progress.
let suggestions = [];
let activeIndex = -1;
let inputFocused = false;
let composing = false;
// True while a pointer press on an option is in flight (pointerdown/mousedown
// seen, click not yet dispatched). Some touch-first browsers blur the input
// despite the preventDefault; the blur handler then defers the close so the
// following click/tap can still accept the option exactly once.
let pointerSelectionPending = false;
let announcedCount = -1;

export function getTags() {
  return [...currentTags];
}

export function setTags(tags) {
  currentTags = [...tags];
  $("#tag-input").value = "";
  closeSuggestions();
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
      // The removed tag becomes suggestible again for the current prefix.
      updateSuggestions();
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
  closeSuggestions();
  renderTagEditor();
}

function isListOpen() {
  return suggestions.length > 0;
}

// All known tags that start with the trimmed input, excluding tags that are
// already selected. Comparison form: both sides are normalized to NFC first,
// so composed and decomposed spellings (e.g. "é" vs "e\u0301") match in both
// directions, then case-folded with toLocaleLowerCase for the active UI
// locale (Unicode-aware locale case folding, e.g. German ß → ss stays
// distinct from s, and Turkish dotted/dotless I rules would apply under a
// "tr" locale — the shipped locales are EN and DE, where I ↔ i). This is a
// locale-aware lowercase fold, not full Unicode case folding; rendered and
// accepted tags always keep their stored spelling. Order is deterministic:
// exact-case prefix matches first, then locale-aware alphabetical, with a
// code-point tiebreaker.
function matchingTags(value) {
  const typed = value.trim();
  if (!typed) return [];
  const locale = document.documentElement.lang || "en";
  const fold = (text) => text.normalize("NFC").toLocaleLowerCase(locale);
  const typedFolded = fold(typed);
  const typedNfc = typed.normalize("NFC");
  const seen = new Set();
  const matches = [];
  for (const tag of getKnownTags()) {
    if (seen.has(tag)) continue;
    seen.add(tag);
    if (currentTags.includes(tag)) continue;
    if (fold(tag).startsWith(typedFolded)) matches.push(tag);
  }
  const caseRank = (tag) => (tag.normalize("NFC").startsWith(typedNfc) ? 0 : 1);
  return matches.sort((a, b) => caseRank(a) - caseRank(b)
    || a.localeCompare(b, locale)
    || (a < b ? -1 : a > b ? 1 : 0));
}

function announce(text) {
  $("#tag-status").textContent = text;
}

function renderSuggestions() {
  const input = $("#tag-input");
  const list = $("#tag-suggestions");
  const open = isListOpen();
  list.replaceChildren(...suggestions.map((tag, index) => {
    const li = document.createElement("li");
    li.id = `tag-option-${index}`;
    li.setAttribute("role", "option");
    li.className = index === activeIndex ? "tag-option active" : "tag-option";
    li.setAttribute("aria-selected", String(index === activeIndex));
    li.textContent = tag;
    // Keep focus in the input: pointerdown (mouse, touch and pen) would
    // otherwise blur the input and close the list before the click can
    // accept the option. mousedown is kept as a fallback for environments
    // without pointer events; both only prevent default (no accept), so the
    // single click/tap handler below never double-accepts.
    const keepFocus = (event) => {
      pointerSelectionPending = true;
      event.preventDefault();
    };
    li.addEventListener("pointerdown", keepFocus);
    li.addEventListener("mousedown", keepFocus);
    // A cancelled press (e.g. the finger drags away) ends the pending
    // selection; if the input was already blurred, close the list now.
    li.addEventListener("pointercancel", () => {
      pointerSelectionPending = false;
      if (!inputFocused) closeSuggestions();
    });
    li.addEventListener("click", () => acceptSuggestion(tag));
    return li;
  }));
  list.hidden = !open;
  input.setAttribute("aria-expanded", String(open));
  if (open && activeIndex >= 0) {
    input.setAttribute("aria-activedescendant", `tag-option-${activeIndex}`);
  } else {
    input.removeAttribute("aria-activedescendant");
  }
  // Announce the count only when it changes, and clear the live region when
  // the list closes so stale text is never re-read.
  if (!open) {
    if (announcedCount !== -1) announce("");
    announcedCount = -1;
  } else if (suggestions.length !== announcedCount) {
    announcedCount = suggestions.length;
    announce(suggestions.length === 1
      ? translate("tagSuggestionsOne")
      : translate("tagSuggestionsMany", { count: suggestions.length }));
  }
}

// Recomputes the matches for the current input. `keepActive` preserves the
// keyboard-active option by value across refreshes (language switch, filter
// reload) so an unrelated update does not reset the user's position.
function updateSuggestions(keepActive = false) {
  const activeTag = keepActive && activeIndex >= 0 ? suggestions[activeIndex] : null;
  suggestions = inputFocused ? matchingTags($("#tag-input").value) : [];
  activeIndex = activeTag === null ? -1 : suggestions.indexOf(activeTag);
  renderSuggestions();
}

function closeSuggestions() {
  suggestions = [];
  activeIndex = -1;
  renderSuggestions();
}

function moveActive(delta) {
  if (!isListOpen()) return;
  if (activeIndex < 0) activeIndex = delta > 0 ? 0 : suggestions.length - 1;
  else activeIndex = (activeIndex + delta + suggestions.length) % suggestions.length;
  renderSuggestions();
}

function acceptSuggestion(tag) {
  pointerSelectionPending = false;
  if (typeof tag !== "string" || !tag) return;
  if (!currentTags.includes(tag)) currentTags = [...currentTags, tag];
  const input = $("#tag-input");
  input.value = "";
  closeSuggestions();
  renderTagEditor();
  announce(translate("tagSuggestionAccepted", { tag }));
  input.focus();
}

export function initTags() {
  const input = $("#tag-input");
  $("#add-tag").addEventListener("click", () => {
    commitTagInput();
    input.focus();
  });
  input.addEventListener("input", () => updateSuggestions());
  input.addEventListener("focus", () => {
    inputFocused = true;
    pointerSelectionPending = false;
    updateSuggestions();
  });
  input.addEventListener("blur", () => {
    inputFocused = false;
    // A blur caused by pressing an option must not destroy the list before
    // the click/tap accepts it (the click handler closes it, pointercancel
    // cleans up an abandoned press). Any other blur closes the list.
    if (pointerSelectionPending) {
      pointerSelectionPending = false;
      return;
    }
    closeSuggestions();
  });
  input.addEventListener("compositionstart", () => {
    composing = true;
  });
  input.addEventListener("compositionend", () => {
    composing = false;
    updateSuggestions();
  });
  input.addEventListener("keydown", (event) => {
    // IME composition: keys build the composed text and must never accept a
    // suggestion or commit a tag prematurely.
    if (composing || event.isComposing) return;
    if (event.key === "Tab" && !event.shiftKey && isListOpen()) {
      // Accept the active suggestion (or the first one) and stay in the
      // input; without an open list Tab keeps its normal focus navigation.
      event.preventDefault();
      acceptSuggestion(suggestions[activeIndex >= 0 ? activeIndex : 0]);
      return;
    }
    if (event.key === "ArrowDown" && isListOpen()) {
      event.preventDefault();
      moveActive(1);
      return;
    }
    if (event.key === "ArrowUp" && isListOpen()) {
      event.preventDefault();
      moveActive(-1);
      return;
    }
    if (event.key === "Escape") {
      if (isListOpen()) {
        event.preventDefault();
        closeSuggestions();
      }
      return;
    }
    if (event.key !== "Enter") return;
    // Enter must never submit the form from the tag input.
    event.preventDefault();
    if (isListOpen() && activeIndex >= 0) acceptSuggestion(suggestions[activeIndex]);
    else commitTagInput();
  });
  // Reuse every completed filter-values load: new tags appear and tags whose
  // last use was deleted disappear, without a request per keystroke. The
  // active input keeps its text and the active option where still present.
  onFilterValuesLoaded(() => updateSuggestions(true));
}

registerRenderer(renderTagEditor);
// A language switch re-sorts the suggestions with the new locale's collation
// and re-renders the (localized) live-region text on the next change.
registerRenderer(() => updateSuggestions(true));
