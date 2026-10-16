// Shared page footer showing the running application version (issue #44).
//
// The version string has a single authoritative runtime source: the server's
// /api/version endpoint (backed by the PPM_VERSION environment variable).
// It is rendered via textContent, so any value is displayed as plain text
// and never interpreted as markup.

import { $ } from "./dom.js";
import { api } from "./api.js";
import { translate, registerRenderer } from "./i18n.js";

let version = "";

export function renderFooterVersion() {
  $("#app-version").textContent = version
    ? translate("versionLabel", { version })
    : "";
}

export async function initFooter() {
  try {
    const data = await api("/api/version");
    version = typeof data.version === "string" ? data.version : "";
  } catch {
    // The footer stays empty when the version cannot be loaded; the
    // application itself keeps working.
    version = "";
  }
  renderFooterVersion();
}

registerRenderer(renderFooterVersion);
