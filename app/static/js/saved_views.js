// Named saved views for the overview. Views contain only overview state; they
// never include or mutate postcard data.
import { translate } from "./i18n.js";

const STORAGE_KEY = "picture-postcard-manager-saved-views";
let getState = () => ({});
let applyState = () => {};
let views = [];

function readViews() {
  try {
    const value = JSON.parse(localStorage.getItem(STORAGE_KEY));
    return Array.isArray(value) ? value.filter((v) => v && typeof v.name === "string" && typeof v.url === "string") : [];
  } catch { return []; }
}
function writeViews() {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(views)); } catch { /* current page still works */ }
}
function currentUrl() {
  const state = getState();
  const url = new URL(window.location.href);
  url.search = "";
  for (const [key, value] of Object.entries(state)) {
    if (Array.isArray(value)) value.forEach((item) => url.searchParams.append(key, item));
    else if (value !== "" && value != null) url.searchParams.set(key, value);
  }
  return `${url.pathname}${url.search}${url.hash}`;
}
function render() {
  const select = document.querySelector("#saved-view-select");
  if (!select) return;
  select.replaceChildren(Object.assign(document.createElement("option"), { value: "", textContent: translate("savedViewChoose") }),
    ...views.map((view) => Object.assign(document.createElement("option"), { value: view.name, textContent: view.name })));
  select.value = "";
  const selected = Boolean(select.value);
  document.querySelector("#saved-view-delete").disabled = !selected;
  document.querySelector("#saved-view-rename").disabled = !selected;
}
export function initSavedViews(callbacks) {
  getState = callbacks.getState;
  applyState = callbacks.applyState;
  views = readViews();
  const select = document.querySelector("#saved-view-select");
  if (!select) return;
  select.addEventListener("change", () => {
    const view = views.find((item) => item.name === select.value);
    if (view) applyState(view.url);
  });
  document.querySelector("#saved-view-save").addEventListener("click", () => {
    const name = window.prompt(translate("savedViewNamePrompt"));
    if (!name?.trim()) return;
    const clean = name.trim();
    const existing = views.find((view) => view.name === clean);
    const item = { name: clean, url: currentUrl() };
    if (existing) Object.assign(existing, item); else views.push(item);
    writeViews(); render();
  });
  document.querySelector("#saved-view-copy").addEventListener("click", async () => {
    const url = new URL(currentUrl(), window.location.href).href;
    try { await navigator.clipboard.writeText(url); } catch {
      window.prompt(translate("savedViewCopyPrompt"), url);
    }
  });
  document.querySelector("#saved-view-rename").addEventListener("click", () => {
    const view = views.find((item) => item.name === select.value);
    const name = window.prompt(translate("savedViewRenamePrompt"), view?.name || "");
    if (!view || !name?.trim() || name.trim() === view.name) return;
    if (views.some((item) => item.name === name.trim())) return;
    view.name = name.trim();
    writeViews(); render();
  });
  document.querySelector("#saved-view-delete").addEventListener("click", () => {
    const name = select.value;
    if (!name) return;
    views = views.filter((view) => view.name !== name);
    writeViews(); render();
  });
  render();
}
export function savedViewsRender() { render(); }
