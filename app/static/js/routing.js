// Fragment-based routing, history handling and view switching.
//
// This module is a leaf of the import graph: it never imports the view
// modules. The route handlers (detail, edit form, new form) and the view
// side effects are injected once via initRouting()/setRoutingHandlers(),
// so detail.js, form.js and overview.js can import navigate()/showView()
// without creating an import cycle.

// Incremented on every route change; async views drop responses for older
// routes by comparing against currentRouteRequest().
let routeRequest = 0;

// Injected by app.js: { openDetail, openEdit, openForm, onBrowse,
// onDetailHidden, onEditHidden }.
let handlers = {};

export function currentRouteRequest() {
  return routeRequest;
}

export function setRoutingHandlers(routeHandlers) {
  handlers = routeHandlers;
}

export function showView(name) {
  if (name !== "detail" && name !== "edit") handlers.onDetailHidden();
  if (name !== "edit") handlers.onEditHidden();
  document.querySelectorAll(".view").forEach((v) => (v.hidden = v.id !== `view-${name}`));
  document.querySelectorAll("nav button").forEach((b) =>
    b.classList.toggle("active", b.dataset.view === name));
  if (name === "browse") return handlers.onBrowse();
}

export function fragmentUuid(fragment) {
  return fragment.match(/^postcards\/([^/]+)/)?.[1] ?? null;
}

// Each history entry records how many app entries lie below it (depth) and how
// many directly preceding entries show the same postcard (run).
export function navigate(fragment, { replace = false } = {}) {
  const current = window.history.state ?? { depth: 0, run: 0 };
  const uuid = fragmentUuid(fragment);
  const state = replace ? current : {
    depth: current.depth + 1,
    run: uuid && uuid === fragmentUuid(window.location.hash.slice(1)) ? current.run + 1 : 0,
  };
  const url = new URL(window.location.href);
  url.hash = fragment;
  window.history[replace ? "replaceState" : "pushState"](state, "", url);
  return route();
}

// Leaves the current postcard: steps back over its entries when they were
// opened in the app, otherwise replaces the current entry with the overview.
export function leavePostcard(keepDetail = false) {
  const { depth = 0, run = 0 } = window.history.state ?? {};
  const steps = keepDetail ? 1 : run + 1;
  if (fragmentUuid(window.location.hash.slice(1)) && steps <= depth) {
    window.history.go(-steps);
    return Promise.resolve();
  }
  return navigate("browse", { replace: true });
}

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

export function route() {
  routeRequest += 1;
  const fragment = window.location.hash.slice(1);
  if (fragment.startsWith("postcards/")) {
    const [id, action, ...rest] = fragment.slice("postcards/".length).split("/");
    if (!UUID_PATTERN.test(id) || rest.length || (action !== undefined && action !== "edit")) {
      return handlers.openDetail(null);
    }
    return action === "edit" ? handlers.openEdit(id) : handlers.openDetail(id);
  }
  if (fragment === "new") {
    handlers.openForm();
  } else {
    return showView(fragment === "data" ? "data" : "browse");
  }
}

export function initRouting(routeHandlers) {
  setRoutingHandlers(routeHandlers);
  document.querySelectorAll("nav button").forEach((b) =>
    b.addEventListener("click", () => navigate(b.id === "nav-new" ? "new" : b.dataset.view)));
  // popstate also covers fragment changes; listening to hashchange too would route twice.
  window.addEventListener("popstate", route);
}
