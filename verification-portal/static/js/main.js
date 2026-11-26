// main.js - tab routing, version banner, health/samples, wiring, boot
"use strict";

// Bind by id only when the element exists. The public page and the staff
// console share this file but not their panels, so a missing control is normal.
// Pass a function name as a string for handlers that live in a script the
// current page does not load (registrar.js is staff-only), so the identifier
// is resolved on click instead of while wiring.
function on(id, ev, fn) {
  const el = document.getElementById(id);
  if (!el) return;
  const handler = typeof fn === "string"
    ? function (e) { const f = window[fn]; if (f) return f.call(this, e); }
    : fn;
  el.addEventListener(ev, handler);
}

// ---- role routing ----
function goTab(tab) {
  document.querySelectorAll(".tabs button").forEach((b) => b.classList.remove("active"));
  document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
  const btn = document.querySelector('[data-tab="' + tab + '"]');
  if (btn) btn.classList.add("active");
  const panel = document.getElementById("panel-" + tab);
  if (panel) panel.classList.add("active");
  if (tab === "log") { loadLog(); loadAnomalies(); loadNotifications(); }
  if (tab === "signers") loadSigners();
  if (tab === "issue") loadApikeys();
  if (tab === "custom") loadCustomList();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

// ---- extras round 5: public-mode banner + verifier identity ----
function initVersion() {
  api("/api/version").then((v) => {
    window.__version = v;
    // Verify-only instance (round 10): keep just Verify / AI Chat / Log.
    if (v.ui_verify_only) {
      ["home", "student", "custom", "issue", "revoke", "signers"].forEach((t) => {
        const tab = document.querySelector('[data-tab="' + t + '"]');
        if (tab) tab.style.display = "none";
        const panel = document.getElementById("panel-" + t);
        if (panel) panel.style.display = "none";
      });
      const hero = document.querySelector(".hero");
      if (hero) hero.style.display = "none";
      const current = document.querySelector(".panel.active");
      if (!current || current.id === "panel-home") goTab("verify");
    }
    if (v.public_mode) {
      ["issue", "revoke", "signers", "custom"].forEach((t) => {
        const tab = document.querySelector('[data-tab="' + t + '"]');
        if (tab) tab.style.display = "none";
        const panel = document.getElementById("panel-" + t);
        if (panel) panel.style.display = "none";
      });
      const registrar = document.getElementById("goRegistrar");
      if (registrar) registrar.classList.add("locked");
      const customCard = document.getElementById("goCustom");
      if (customCard) customCard.classList.add("locked");
      const note = document.getElementById("publicNote");
      if (note) note.style.display = "block";
      const hero = document.querySelector(".hero");
      const banner = document.createElement("div");
      banner.className = "badge";
      banner.textContent = "公开验证模式 Public verifier mode —— 本实例仅可验证，签发/注销已禁用";
      banner.style.cssText = "display:block;margin:0 0 18px;padding:10px 14px;border-radius:10px;background:#fff7e0;border:1px solid #f0c36d;font-size:13px;font-weight:600;color:#7a5b12";
      (hero || document.body).prepend(banner);
    }
    // U13 F7: say the quiet part out loud. A demo instance with no token
    // accepts anyone on the admin routes; the note sits where the public-mode
    // note sits, so it reads as a state of the deployment, not a page error.
    if (v.demo_open && !v.public_mode) {
      const note = document.getElementById("publicNote");
      if (note) {
        note.textContent = "演示模式（DEMO_OPEN=1）：本实例没有配置 staff token，签发、注销与签发方接口对本机任何访问者开放，仅适合本机演示。设置 ADMIN_TOKEN（窄权限再加 ISSUER_TOKEN）并把 DEMO_OPEN 设为 0 即可关闭。";
        note.style.display = "block";
      }
    }
    // U15: an unverifiable chain makes every verdict read INVALID. A visitor
    // would take that as "this credential is fake", so say plainly that the
    // problem is on the server.
    const integ = (v.chain || {}).integrity || {};
    if (integ.ok === false) {
      const bad = (integ.bad_blocks || []).map((h) => "#" + h).join(", ");
      const banner = document.createElement("div");
      banner.className = "badge";
      const note = document.createElement("span");
      note.textContent = "⚠ 本实例的链完整性校验失败" +
        (bad ? "（区块 " + bad + "）" : "") +
        "：所有判定都会显示 INVALID，问题在服务端而不是这张凭证。运行 scripts/smoke_portal.py 复现。";
      const link = document.createElement("a");
      link.href = "/healthz";
      link.target = "_blank";
      link.rel = "noopener";
      link.textContent = "查看原始检查 →";
      link.style.cssText = "margin-left:8px;color:#8b1a1a;text-decoration:underline";
      banner.append(note, link);
      banner.style.cssText = "display:block;margin:0 0 18px;padding:10px 14px;border-radius:10px;background:#fee2e2;border:1px solid #f0a6a6;font-size:13px;font-weight:600;color:#8b1a1a";
      const hero = document.querySelector(".hero");
      (hero || document.body).prepend(banner);
    }
  }).catch(() => { /* version unavailable */ });
}

// ---- health + samples ----
async function refreshHealth() {
  try {
    const h = await api("/healthz");
    const signer = (h.signers && h.signers[0] && h.signers[0].name) || "—";
    $("health").textContent = h.chain_name + " · " + h.content_hash_algo + " · 高度 " + h.height + " · 签发方: " + signer;
    $("statHeight").textContent = h.height;
    $("statSigners").textContent = (h.signers || []).length;
    $("statAlgo").textContent = h.content_hash_algo;
    loadLog();
  } catch (e) { $("health").textContent = "无法连接 API —— 服务器是否已启动？"; }
}
async function loadSamples() {
  try {
    const s = await api("/api/demo/credentials");
    Object.assign(samples, s);
  } catch (e) { /* samples unavailable */ }
}
function fillSample(key, target) {
  const s = samples[key];
  if (s) { $(target).value = JSON.stringify(s.document, null, 2); hideErr($("err")); }
}

// ---- wiring ----
document.querySelectorAll(".tabs button").forEach((btn) => {
  btn.addEventListener("click", () => goTab(btn.dataset.tab));
});
on("goVerify", "click", () => goTab("verify"));
// The holder card exists on the public page only, not in the staff console.
on("goStudent", "click", () => goTab("student"));
on("goRegistrar", "click", () => {
  if (window.__version && window.__version.public_mode) {
    showErr($("err"), "此公开实例不支持签发。请运行方使用管理员模式（PUBLIC_MODE=0）。");
    return;
  }
  goTab("issue");
});
on("goCustom", "click", () => {
  if (window.__version && window.__version.public_mode) {
    showErr($("err"), "此公开实例不支持签发。请运行方使用管理员模式（PUBLIC_MODE=0）。");
    return;
  }
  goTab("custom");
});

// Sample + batch + apikeys + receipt listeners.
// U12 R1 split the page in two: the public page no longer contains the issue,
// revoke or signers panels (they live in staff.html). Every binding below goes
// through on(), which skips a missing element — otherwise one null would abort
// the rest of this file and leave the public page stuck on "connecting…".
["sampleBtn-valid", "sampleBtn-revoked", "sampleBtn-invalid"].forEach((id) => on(id, "click", () => verifySample(id.replace("sampleBtn-", ""))));
["sampleBtn2-valid", "sampleBtn2-revoked", "sampleBtn2-invalid"].forEach((id) => on(id, "click", () => verifySample(id.replace("sampleBtn2-", ""))));
on("verifyHashBtn", "click", "verifyHash");
on("hashinput", "keydown", (e) => { if (e.key === "Enter") verifyHash(); });
on("verifyDocBtn", "click", "verifyDocument");
on("batchBtn", "click", "verifyBatch");
on("batchCsvBtn", "click", "downloadBatchCsv");
on("receiptBtn", "click", () => downloadReceipt(lastResult));
on("printReceiptBtn", "click", () => printReceipt(lastResult));
on("copyHash", "click", () => navigator.clipboard && navigator.clipboard.writeText($("hashValue").textContent));
on("pdfFetchBtn", "click", "fetchPdf");
on("issueBtn", "click", "issueDoc");
on("issueLoadDiploma", "click", () => fillSample("diploma", "issuejson"));
on("issueExtractBtn", "click", () => $("issuePdfInput").click());
on("issuePdfInput", "change", (e) => {
  const f = e.target.files && e.target.files[0];
  if (!f) return;
  const note = $("issueExtractNote");
  note.className = "extract-note on warn";
  note.innerHTML = "<span class=\"en-badge\">提取中</span>正在读取 " + esc(f.name) + " …";
  extractPdfInto(f, "issuejson", "issueExtractNote")
    .then(() => { note.innerHTML = note.innerHTML.replace("<span class=\"en-badge\">提取中</span>正在读取", "<span class=\"en-badge\">已填充</span>"); })
    .catch(() => { /* error note already rendered */ });
});
on("revokeBtn", "click", "revokeDoc");
const holderBtnEl = $("holderBtn"); if (holderBtnEl) holderBtnEl.addEventListener("click", openHolder);
const mintBtnEl = $("mintLinkBtn"); if (mintBtnEl) mintBtnEl.addEventListener("click", mintHolderLink);
on("addSignerBtn", "click", "addSigner");
on("loadDiploma", "click", () => fillSample("diploma", "docjson"));
on("loadTranscript", "click", () => fillSample("transcript", "docjson"));
on("apikeyCreateBtn", "click", "createApikey");
on("batchRegTemplateBtn", "click", "downloadTemplate");
on("batchRegBtn", "click", "runBatchIssue");
on("batchRegText", "input", "previewBatch");
on("batchRegCsv", "change", () => {
  const f = $("batchRegCsv").files && $("batchRegCsv").files[0];
  if (!f) return;
  const reader = new FileReader();
  reader.onload = () => { $("batchRegText").value = reader.result; previewBatch(); };
  reader.readAsText(f);
});
const apikeyTableEl = document.getElementById("apikeyTable");
if (apikeyTableEl) apikeyTableEl.addEventListener("click", (e) => {
  const b = e.target.closest("[data-revoke]");
  if (!b) return;
  if (!confirm("撤销 API 密钥 " + b.getAttribute("data-revoke") + "？")) return;
  api("/api/admin/apikeys/" + b.getAttribute("data-revoke"), { method: "DELETE" })
    .then(() => loadApikeys())
    .catch((err) => showErr($("apikeyErr"), err.message));
});
const studentWrap = document.getElementById("studentWrap");
if (studentWrap) studentWrap.addEventListener("click", (e) => {
  const b = e.target.closest("[data-share]");
  if (!b) return;
  const url = (window.__version && window.__version.public_base_url) || location.origin;
  const share = url + "/verify?hash=" + b.getAttribute("data-share");
  navigator.clipboard && navigator.clipboard.writeText(share);
  b.textContent = "已复制!";
  setTimeout(() => { b.textContent = "分享链接"; }, 1500);
});

// ---- U13 F4: role-aware console ----
// What a session may use is decided server-side; this only stops the console
// from offering controls that would 401 on click. demo_open (no token
// configured) grants everything by design, and the badge says so instead of
// pretending auth is switched on.
var ROLE_TABS = { custom: ["admin"], revoke: ["admin"], signers: ["admin"] };

function applyRole(info) {
  var role = info && info.role;
  var demo = !!(info && info.demo_open);
  var badge = document.getElementById("staffRole");
  var left = info && info.session_seconds_left;

  function paint() {
    if (!badge) return;
    var name = demo ? "DEMO · 未配置 token"
      : (role ? "角色 " + String(role).toUpperCase() : "未登录");
    if (typeof left === "number" && left > 0) {
      name += " · 会话剩 " + Math.ceil(left / 60) + " 分钟";
    } else if (left === 0) {
      name += " · 会话已过期，请重新登录";
    }
    badge.textContent = name;
  }

  if (badge) { badge.style.display = "inline-block"; paint(); }

  // U13 F6: tick the countdown locally instead of polling the server.
  if (typeof left === "number" && left > 0) {
    (function tick() {
      setTimeout(function () {
        left = Math.max(0, left - 1);
        paint();
        if (left > 0) { tick(); return; }
        if (!demo && role) window.location.replace("/staff/login");
      }, 1000);
    })();
  }

  Object.keys(ROLE_TABS).forEach(function (t) {
    if (demo || ROLE_TABS[t].indexOf(role) >= 0) return;
    var b = document.querySelector('[data-tab="' + t + '"]');
    if (b) b.style.display = "none";
    var p = document.getElementById("panel-" + t);
    if (p) p.style.display = "none";
    var card = document.getElementById(t === "custom" ? "goCustom" : "");
    if (card) card.style.display = "none";
  });
  document.querySelectorAll("[data-role]").forEach(function (el) {
    var allowed = String(el.getAttribute("data-role") || "").split(" ");
    el.style.display = (demo || allowed.indexOf(role) >= 0) ? "" : "none";
  });
  var active = document.querySelector(".panel.active");
  if (active && active.style.display === "none") goTab("home");
}

function initRole() {
  var badge = document.getElementById("staffRole");
  if (!badge) return;  // public page: nothing to hide
  api("/api/staff/whoami").then(applyRole).catch(function (e) {
    // Say why instead of leaving a blank badge: a silently empty role chip
    // looks like a styling bug and hides a real auth problem.
    badge.style.display = "inline-block";
    badge.textContent = "角色未知（whoami 失败：" + (e && e.message ? e.message : "?") + "）";
  });
}

// ---- boot ----
refreshHealth();
initVersion();
initRole();
loadCredSamples();
loadSamples();
loadSuggestions();
loadGenHint();

// Deep-link / QR scan target: /verify and /verify?hash=... land on the Verify tab
const params = new URLSearchParams(location.search);
const qh = params.get("hash");
if (qh || location.pathname.endsWith("/verify")) {
  goTab("verify");
  if (qh) { $("hashinput").value = qh; verifyHash(); }
}

// U12 R2: staff sign-out. U14 F6 adds "every device": the same handler posts
// to /staff/logout/all, which drops every session of this role server-side.
document.addEventListener("click", function (ev) {
  var btn = ev.target && ev.target.closest
    ? ev.target.closest("#staffLogout, #staffLogoutAll") : null;
  if (!btn) return;
  btn.disabled = true;
  var all = btn.id === "staffLogoutAll";
  fetch(all ? "/staff/logout/all" : "/staff/logout",
        { method: "POST", credentials: "same-origin" })
    .catch(function () { /* still leave the page */ })
    .then(function () { window.location.replace("/staff/login"); });
});
