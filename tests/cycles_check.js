"use strict";

// Builds the static import graph of app.js and app/static/js/*.js and fails
// on any import cycle, printing each cycle it finds. Run via:
//   node tests/cycles_check.js [staticDir]
// The module graph must stay acyclic: shared primitives live in leaf modules
// and routing receives its handlers by injection from app.js (see README).
const fs = require("node:fs");
const path = require("node:path");

const staticDir = path.resolve(process.argv[2] ?? path.join(__dirname, "../app/static"));

// file (relative to staticDir, posix) -> list of imported files.
function buildGraph() {
  const graph = new Map();
  const files = ["app.js",
    ...fs.readdirSync(path.join(staticDir, "js"))
      .filter((name) => name.endsWith(".js"))
      .map((name) => `js/${name}`)];
  for (const file of files) {
    const source = fs.readFileSync(path.join(staticDir, file), "utf8");
    const imports = [];
    for (const match of source.matchAll(/^import\s[^;]*?from\s+["'](.+?)["'];?\s*$/gm)) {
      const base = path.posix.dirname(file);
      imports.push(path.posix.normalize(path.posix.join(base, match[1])));
    }
    graph.set(file, imports);
  }
  return graph;
}

function findCycles(graph) {
  const cycles = [];
  const visiting = new Set();
  const done = new Set();
  const stack = [];

  function visit(node) {
    if (done.has(node)) return;
    if (visiting.has(node)) {
      cycles.push([...stack.slice(stack.indexOf(node)), node]);
      return;
    }
    visiting.add(node);
    stack.push(node);
    for (const dep of graph.get(node) ?? []) visit(dep);
    stack.pop();
    visiting.delete(node);
    done.add(node);
  }

  for (const node of graph.keys()) visit(node);
  return cycles;
}

const graph = buildGraph();
const cycles = findCycles(graph);
if (cycles.length) {
  console.error("Import cycles detected:");
  for (const cycle of cycles) console.error(`  ${cycle.join(" -> ")}`);
  process.exitCode = 1;
} else {
  console.log(`Import graph of ${graph.size} modules is acyclic.`);
}
