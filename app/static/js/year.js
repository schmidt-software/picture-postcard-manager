// Editable year combobox for the entry form (issue #65).
//
// The year stays a free-form text field: anything typed is saved verbatim
// ("1927", "around 1800", "ca. 1960", "unknown", or empty). The distinct
// year values already stored in the collection are offered as suggestions,
// sourced from the cached filter-values response maintained by filters.js:
// no request is sent per keystroke, and every place that reloads the filter
// dropdowns (save, delete, JSON import, bulk import, entering the overview)
// refreshes the suggestions through onFilterValuesLoaded. A failed load
// simply leaves the list empty, so free-form entry always keeps working.
//
// The pointer-press/blur state machine mirrors the tag autocomplete
// (js/tags.js): a press on an option keeps focus in the input where
// possible, and a touch-first blur only schedules a short deferred close so
// the tap's click can still accept the option. See tags.js for the detailed
// rationale of every terminal path.

import { $ } from "./dom.js";
import { translate, registerRenderer } from "./i18n.js";
import { getKnownYears, onFilterValuesLoaded } from "./filters.js";

let yearSuggestions = [];
let yearActiveIndex = -1;
let yearInputFocused = false;
let yearComposing = false;
let yearPointerSelectionPending = false;
let yearPendingCloseTimer = null;
let yearSuggestionEpoch = 0;
let yearAnnouncedCount = -1;

function isYearListOpen() {
  return yearSuggestions.length > 0;
}

// Known distinct year values matching the typed text. An empty input offers
// every known value (the classic editable-combobox behavior), a non-empty
// input narrows to case-insensitive prefix matches (NFC-normalized, locale
// case fold — see tags.js). Stored spellings are preserved; order is
// deterministic: exact-case prefix matches first, then locale-aware
// alphabetical with a code-point tiebreaker.
function matchingYears(value) {
  const typed = value.trim();
  const locale = document.documentElement.lang || "en";
  const fold = (text) => text.normalize("NFC").toLocaleLowerCase(locale);
  const typedFolded = fold(typed);
  const typedNfc = typed.normalize("NFC");
  const seen = new Set();
  const matches = [];
  for (const year of getKnownYears()) {
    if (seen.has(year)) continue;
    seen.add(year);
    if (!typed || fold(year).startsWith(typedFolded)) matches.push(year);
  }
  const caseRank = (year) => (!typed || year.normalize("NFC").startsWith(typedNfc) ? 0 : 1);
  return matches.sort((a, b) => caseRank(a) - caseRank(b)
    || a.localeCompare(b, locale)
    || (a < b ? -1 : a > b ? 1 : 0));
}

function announceYear(text) {
  $("#year-status").textContent = text;
}

function renderYearSuggestions() {
  const input = $("#year-input");
  const list = $("#year-suggestions");
  const open = isYearListOpen();
  list.replaceChildren(...yearSuggestions.map((year, index) => {
    const li = document.createElement("li");
    li.id = `year-option-${index}`;
    li.setAttribute("role", "option");
    li.className = index === yearActiveIndex ? "tag-option active" : "tag-option";
    li.setAttribute("aria-selected", String(index === yearActiveIndex));
    li.textContent = year;
    const keepFocus = (event) => {
      yearPointerSelectionPending = true;
      event.preventDefault();
    };
    li.addEventListener("pointerdown", keepFocus);
    li.addEventListener("mousedown", keepFocus);
    li.addEventListener("pointercancel", abandonYearPointerSelection);
    li.addEventListener("pointerleave", abandonYearPointerSelection);
    li.addEventListener("click", () => acceptYearSuggestion(year));
    return li;
  }));
  list.hidden = !open;
  input.setAttribute("aria-expanded", String(open));
  if (open && yearActiveIndex >= 0) {
    input.setAttribute("aria-activedescendant", `year-option-${yearActiveIndex}`);
  } else {
    input.removeAttribute("aria-activedescendant");
  }
  if (!open) {
    if (yearAnnouncedCount !== -1) announceYear("");
    yearAnnouncedCount = -1;
  } else if (yearSuggestions.length !== yearAnnouncedCount) {
    yearAnnouncedCount = yearSuggestions.length;
    announceYear(yearSuggestions.length === 1
      ? translate("yearSuggestionsOne")
      : translate("yearSuggestionsMany", { count: yearSuggestions.length }));
  }
}

// Recomputes the matches for the current input. `keepActive` preserves the
// keyboard-active option by value across refreshes (language switch, filter
// reload) so an unrelated update does not reset the user's position.
function updateYearSuggestions(keepActive = false) {
  const activeYear = keepActive && yearActiveIndex >= 0 ? yearSuggestions[yearActiveIndex] : null;
  yearSuggestions = yearInputFocused ? matchingYears($("#year-input").value) : [];
  yearActiveIndex = activeYear === null ? -1 : yearSuggestions.indexOf(activeYear);
  renderYearSuggestions();
}

function closeYearSuggestions() {
  yearSuggestionEpoch += 1;
  yearPointerSelectionPending = false;
  if (yearPendingCloseTimer !== null) {
    clearTimeout(yearPendingCloseTimer);
    yearPendingCloseTimer = null;
  }
  yearSuggestions = [];
  yearActiveIndex = -1;
  renderYearSuggestions();
}

function abandonYearPointerSelection() {
  if (!yearPointerSelectionPending) return;
  yearPointerSelectionPending = false;
  if (!yearInputFocused) closeYearSuggestions();
}

function moveYearActive(delta) {
  if (!isYearListOpen()) return;
  if (yearActiveIndex < 0) yearActiveIndex = delta > 0 ? 0 : yearSuggestions.length - 1;
  else yearActiveIndex = (yearActiveIndex + delta + yearSuggestions.length) % yearSuggestions.length;
  renderYearSuggestions();
}

// Selecting a suggestion fills the field with the stored spelling, closes the
// list and keeps focus in the input so the value can still be edited freely.
function acceptYearSuggestion(year) {
  if (typeof year !== "string" || !year) return;
  const input = $("#year-input");
  input.value = year;
  closeYearSuggestions();
  announceYear(translate("yearSuggestionAccepted", { year }));
  input.focus();
}

// Route/view lifecycle cleanup: synchronously closes the suggestion list,
// resolves any pending pointer press and cancels the deferred blur-close
// timer. The typed year value is intentionally left alone.
export function resetYearSuggestions() {
  yearInputFocused = false;
  closeYearSuggestions();
}

export function initYear() {
  const input = $("#year-input");
  input.addEventListener("input", () => updateYearSuggestions());
  input.addEventListener("focus", () => {
    yearInputFocused = true;
    yearPointerSelectionPending = false;
    if (yearPendingCloseTimer !== null) {
      clearTimeout(yearPendingCloseTimer);
      yearPendingCloseTimer = null;
    }
    updateYearSuggestions();
  });
  input.addEventListener("blur", () => {
    yearInputFocused = false;
    // See tags.js: a press-caused blur defers the close so the tap's click
    // can still accept; any other blur closes the list immediately.
    if (yearPointerSelectionPending) {
      if (yearPendingCloseTimer === null) {
        const epoch = yearSuggestionEpoch;
        yearPendingCloseTimer = setTimeout(() => {
          yearPendingCloseTimer = null;
          if (epoch !== yearSuggestionEpoch) return;
          yearPointerSelectionPending = false;
          if (!yearInputFocused) closeYearSuggestions();
        }, 250);
      }
      return;
    }
    closeYearSuggestions();
  });
  input.addEventListener("compositionstart", () => {
    yearComposing = true;
  });
  input.addEventListener("compositionend", () => {
    yearComposing = false;
    updateYearSuggestions();
  });
  input.addEventListener("keydown", (event) => {
    // IME composition: keys build the composed text and must never accept a
    // suggestion prematurely.
    if (yearComposing || event.isComposing) return;
    if (event.key === "ArrowDown" && isYearListOpen()) {
      event.preventDefault();
      moveYearActive(1);
      return;
    }
    if (event.key === "ArrowUp" && isYearListOpen()) {
      event.preventDefault();
      moveYearActive(-1);
      return;
    }
    if (event.key === "Escape") {
      // Escape only closes the open list; the typed value stays. A second
      // Escape is not swallowed so dialog/view shortcuts keep working.
      if (isYearListOpen()) {
        event.preventDefault();
        closeYearSuggestions();
      }
      return;
    }
    if (event.key !== "Enter") return;
    // Enter with a keyboard-active suggestion accepts it and must not submit
    // the form; Enter without one keeps the browser's normal submit, after
    // closing the list so the popup never outlives the form.
    if (isYearListOpen() && yearActiveIndex >= 0) {
      event.preventDefault();
      acceptYearSuggestion(yearSuggestions[yearActiveIndex]);
      return;
    }
    if (isYearListOpen()) closeYearSuggestions();
  });
  // Reuse every completed filter-values load: new year values appear and
  // values whose last use was deleted disappear, without a request per
  // keystroke. The input keeps its text and the active option where present.
  onFilterValuesLoaded(() => updateYearSuggestions(true));
}

// A language switch re-sorts the suggestions with the new locale's collation
// and re-renders the (localized) live-region text on the next change.
registerRenderer(() => updateYearSuggestions(true));
