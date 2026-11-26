// core.js - shared state, fetch client, escaping, downloads (U6.1)
"use strict";

const $ = (id) => document.getElementById(id);
const samples = {};
let selectedFile = null;
let lastResult = null;
let lastIssuedHash = "";
let _lastBatch = null;

async function api(path, opts) {
  const res = await fetch(path, opts);
  let data = null;
  try { data = await res.json(); } catch (e) { data = { detail: res.statusText }; }
  if (!res.ok) throw new Error(data && data.detail ? data.detail : ("HTTP " + res.status));
  return data;
}
function showErr(el, msg) { el.textContent = msg; el.style.display = "block"; }
function hideErr(el) { el.style.display = "none"; }

// U6.2: escaping is a pure string function, not a DOM trick. The old version
// built a <div>, set textContent, and read back innerHTML — correct, but it
// could only run in a browser, so nothing in the test suite could assert that
// "<img onerror=...>" actually gets neutralised. This one is testable in Node
// and has a single place to audit.
const HTML_ESCAPES = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};
function escapeHtml(s) {
  if (s === null || s === undefined) return "";
  return String(s).replace(/[&<>"']/g, (ch) => HTML_ESCAPES[ch]);
}
function esc(s) { return escapeHtml(s); }

function downloadText(name, text, type) {
  const blob = new Blob([text], { type: type || "text/plain" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}
