"use strict";

const $ = (sel) => document.querySelector(sel);

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (res.status === 204) return null;
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

function showMessage(text, isError = false) {
  const el = $("#message");
  el.textContent = text;
  el.className = isError ? "error" : "";
  el.hidden = false;
  clearTimeout(showMessage.timer);
  showMessage.timer = setTimeout(() => (el.hidden = true), 4000);
}

function showView(name) {
  document.querySelectorAll(".view").forEach((v) => (v.hidden = v.id !== `view-${name}`));
  document.querySelectorAll("nav button").forEach((b) =>
    b.classList.toggle("active", b.dataset.view === name));
  if (name === "browse") loadList();
}

// --- Browse -----------------------------------------------------------------

async function loadList() {
  const q = $("#search").value.trim();
  const items = await api(`/api/postcards${q ? `?q=${encodeURIComponent(q)}` : ""}`);
  const tbody = $("#postcard-list");
  tbody.replaceChildren(...items.map((p) => {
    const tr = document.createElement("tr");
    for (const value of [p.id, p.title, p.notes, p.updated_at]) {
      const td = document.createElement("td");
      td.textContent = value;
      tr.append(td);
    }
    tr.addEventListener("click", () => openForm(p));
    return tr;
  }));
  $("#empty-hint").hidden = items.length > 0;
}

// --- Entry form -------------------------------------------------------------

function openForm(postcard = null) {
  const form = $("#postcard-form");
  form.reset();
  form.elements.id.value = postcard?.id ?? "";
  for (const [key, value] of Object.entries(postcard || {})) {
    if (form.elements[key]) form.elements[key].value = value;
  }
  $("#form-title").textContent = postcard ? `Edit postcard #${postcard.id}` : "New postcard";
  $("#delete").hidden = !postcard;
  showView("edit");
}

$("#postcard-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const data = Object.fromEntries(new FormData(e.target));
  const id = data.id;
  delete data.id;
  try {
    if (id) await api(`/api/postcards/${id}`, { method: "PUT", body: JSON.stringify(data) });
    else await api("/api/postcards", { method: "POST", body: JSON.stringify(data) });
    showMessage("Postcard saved.");
    showView("browse");
  } catch (err) {
    showMessage(err.message, true);
  }
});

$("#delete").addEventListener("click", async () => {
  const id = $("#postcard-form").elements.id.value;
  if (!id || !confirm("Delete this postcard?")) return;
  try {
    await api(`/api/postcards/${id}`, { method: "DELETE" });
    showMessage("Postcard deleted.");
    showView("browse");
  } catch (err) {
    showMessage(err.message, true);
  }
});

$("#cancel").addEventListener("click", () => showView("browse"));

// --- Import -----------------------------------------------------------------

$("#import-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  const mode = form.elements.mode.value;
  if (mode === "replace" && !confirm("Replace ALL existing postcards?")) return;
  try {
    const text = await form.elements.file.files[0].text();
    const result = await api(`/api/import?mode=${mode}`, { method: "POST", body: text });
    showMessage(`${result.imported} postcards imported.`);
    form.reset();
  } catch (err) {
    showMessage(err.message, true);
  }
});

// --- Init -------------------------------------------------------------------

document.querySelectorAll("nav button").forEach((b) =>
  b.addEventListener("click", () => (b.id === "nav-new" ? openForm() : showView(b.dataset.view))));

let searchTimer;
$("#search").addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(loadList, 250);
});

loadList();
