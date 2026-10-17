"use strict";

// Concatenates the ES modules into one classic script for the vm-based
// runtime tests: import lines are dropped and export keywords stripped, so the
// modules share a single scope exactly like the former monolithic app.js.
const fs = require("node:fs");
const path = require("node:path");

const MODULE_ORDER = [
  "js/dom.js", "js/api.js", "js/i18n.js", "js/footer.js", "js/feedback.js", "js/preview.js",
  "js/upload.js", "js/routing.js", "js/sorting.js",
  "js/filters.js", "js/tags.js", "js/detail.js", "js/overview.js", "js/form.js",
  "js/import.js", "js/bulk.js", "app.js",
];

function bundleSource(staticDir) {
  return MODULE_ORDER.map((file) =>
    fs.readFileSync(path.join(staticDir, file), "utf8")
      .replace(/^import .*$/gm, "")
      .replace(/^export /gm, "")).join("\n");
}

module.exports = { bundleSource, MODULE_ORDER };
