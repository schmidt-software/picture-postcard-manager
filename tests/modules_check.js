"use strict";

// Verifies that every ES module parses and that all imports resolve, without
// executing them (no DOM needed). Run via:
//   node --experimental-vm-modules tests/modules_check.js
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

if (typeof vm.SourceTextModule !== "function") {
  console.log("vm modules unavailable; parse check skipped.");
  process.exit(0);
}

const staticDir = path.join(__dirname, "../app/static");
const { MODULE_ORDER } = require("./bundle");

async function check() {
  const context = vm.createContext({});
  const cache = new Map();

  function load(file) {
    if (cache.has(file)) return cache.get(file);
    const source = fs.readFileSync(path.join(staticDir, file), "utf8");
    const module = new vm.SourceTextModule(source, { identifier: file, context });
    cache.set(file, module);
    return module;
  }

  const entry = load("app.js");
  await entry.link((specifier, referencing) => {
    const base = path.posix.dirname(referencing.identifier);
    const resolved = path.posix.normalize(path.posix.join(base, specifier));
    assert.ok(fs.existsSync(path.join(staticDir, resolved)),
      `${referencing.identifier} imports missing module ${specifier}`);
    return load(resolved);
  });
  // Linking succeeded: every import statement resolves to an existing export.
  for (const file of MODULE_ORDER) {
    assert.ok(cache.has(file) || file === "app.js", `bundle order lists unused module ${file}`);
  }
  console.log("Module graph parse and link checks passed.");
}

check().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
