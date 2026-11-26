// Minimal DOM/Net harness: loads the portal's classic scripts into one VM
// realm (same semantics as <script> tags sharing the global scope) and runs
// assertions.js against them. No browser, no npm dependencies.
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

const STATIC = path.resolve(process.argv[2] || "static");
const FILES = [
  "js/core.js", "js/format.js", "js/verify.js", "js/registrar.js",
  "js/student.js", "js/log.js", "js/chat.js", "js/main.js",
];

const failures = [];
let checks = 0;
function assert(cond, msg) {
  checks += 1;
  if (!cond) failures.push(msg);
}

function makeEl(id) {
  const el = {
    id,
    _html: "",
    textContent: "",
    value: "",
    files: null,
    style: {},
    dataset: {},
    children: [],
    listeners: {},
    classList: { add() {}, remove() {}, contains() { return false; }, toggle() {} },
    get innerHTML() { return this._html; },
    set innerHTML(v) { this._html = String(v); },
    appendChild(c) { this.children.push(c); return c; },
    addEventListener(ev, fn) { this.listeners[ev] = fn; },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    scrollIntoView() {},
    focus() {},
    click() {},
    remove() {},
    closest() { return null; },
    getAttribute() { return ""; },
    setAttribute() {},
    scrollTop: 0,
    scrollHeight: 0,
    open() { return false; },
    write() {},
    close() {},
    print() {},
  };
  return el;
}

const registry = new Map();
const document = {
  getElementById(id) {
    if (!registry.has(id)) registry.set(id, makeEl(id));
    return registry.get(id);
  },
  createElement(tag) { return makeEl(tag); },
  querySelectorAll() { return []; },
  querySelector() { return null; },
  addEventListener() {},
  body: makeEl("body"),
};

const routes = new Map();
function fetchStub(url) {
  const body = routes.get(url);
  if (body === undefined) {
    return Promise.reject(new Error("no stub for " + url));
  }
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
}

const ctx = {
  console,
  setTimeout,
  clearTimeout,
  JSON,
  Math,
  Date,
  Promise,
  String,
  Number,
  Object,
  Array,
  Error,
  encodeURIComponent,
  Blob: class Blob { constructor(parts) { this.parts = parts; } },
  URL: { createObjectURL: () => "blob:stub", revokeObjectURL() {} },
  fetch: fetchStub,
  document,
  location: { origin: "http://portal.test", search: "", pathname: "/" },
  navigator: { clipboard: { writeText: () => Promise.resolve() } },
  localStorage: {
    _s: {},
    getItem(k) { return this._s[k] ?? null; },
    setItem(k, v) { this._s[k] = String(v); },
  },
  confirm: () => true,
  assert,
  routes,
  URLSearchParams,
};
ctx.window = ctx;
ctx.globalThis = ctx;
ctx.window.scrollTo = () => {};
vm.createContext(ctx);

// Boot-time endpoints: main.js runs its wiring and boot calls on load, so the
// split is exercised end-to-end (missing global / wrong load order shows up
// here, not only in a browser).
routes.set("/api/version", { app: "Gef26 verifier", version: "6.0.0", public_mode: false, ui_verify_only: false, chain: { name: "demo", height: 3 } });
routes.set("/healthz", { chain_name: "demo", content_hash_algo: "sha3_512", height: 3, signers: [{ name: "S" }] });
routes.set("/api/demo/credentials", { diploma: { document: {} }, transcript: { document: {} } });
routes.set("/api/chat/suggestions", { suggestions: ["q1"] });
routes.set("/api/rag/status", { generator: "offline", embedder: "hash-ngrams-v1", index_entries: 8 });

for (const rel of FILES) {
  const file = path.join(STATIC, rel);
  const code = fs.readFileSync(file, "utf8");
  try {
    vm.runInContext(code, ctx, { filename: rel });
  } catch (e) {
    assert(false, `${rel} failed to load: ${e.message}`);
  }
}

const asserts = fs.readFileSync(
  path.join(path.dirname(new URL(import.meta.url).pathname.replace(/^\/(\w:)/, "$1")), "assertions.js"),
  "utf8",
);
vm.runInContext(asserts, ctx, { filename: "assertions.js" });

// ---- async path: the three log tables feed straight from the API ----
const EVIL = '<img src=x onerror="alert(1)">';
routes.set("/api/log", {
  total_verifications: 1,
  verifications: [{ time: 1600000000, hash_prefix: EVIL, verdict: "NOT FOUND" }],
  chain_events: [{ height: EVIL, action: EVIL, hash_prefix: EVIL }],
});
routes.set("/api/anomalies", {
  method: EVIL,
  threshold: EVIL,
  hourly_issues: [],
  anomalies: [{ severity: EVIL, signer: EVIL, credential_count: EVIL, threshold: EVIL, reasons: [EVIL], last_height: EVIL }],
});
routes.set("/api/notifications", {
  notifications: [{ time: 1600000000, to: EVIL, status: EVIL, detail: EVIL }],
});

await ctx.loadLog();
await ctx.loadAnomalies();
await ctx.loadNotifications();
for (const id of ["logTable", "chainTable", "anomalyBox", "notifTable"]) {
  const html = registry.get(id).innerHTML;
  assert(html.indexOf("<img") === -1, `${id} must not emit a raw <img> from API data`);
  assert(html.indexOf("&lt;img") !== -1 || html.indexOf(EVIL) === -1,
    `${id} must escape the injected value`);
}

for (const f of failures) console.log("FAIL: " + f);
console.log(`${checks - failures.length}/${checks} frontend assertions passed`);
process.exit(failures.length ? 1 : 0);
