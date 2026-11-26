// verify.js - verify tab: dropzone, document/hash/PDF verify, samples, batch
"use strict";

// ---- one-click sample verification ----
function sampleEntry(creds, kind) {
  if (kind === "invalid") return null;
  if (kind === "valid") return creds["diploma"] || creds["valid"] || null;
  return creds["revoked_sample"] || creds["revoked"] || null;
}
async function loadCredSamples() {
  try {
    const creds = await api("/api/demo/credentials");
    ["valid", "revoked", "invalid"].forEach((kind) => {
      const ids = ["sampleBtn-" + kind, "sampleBtn2-" + kind];
      ids.forEach((id) => {
        const b = document.getElementById(id);
        if (!b) return;
        const entry = sampleEntry(creds, kind);
        b.disabled = kind !== "invalid" && !entry;
        if (!entry && kind === "revoked") {
          b.title = "注销样例仅在公开验证模式可用（需链上已注销记录）";
          b.textContent = "↩ 已注销（公开模式）";
        } else if (entry) {
          b.title = entry.hashed_document.slice(0, 16) + "…";
        }
      });
    });
  } catch (e) { /* samples unavailable */ }
}
async function verifySample(kind) {
  hideErr($("err"));
  try {
    const creds = await api("/api/demo/credentials");
    let h;
    if (kind === "invalid") {
      h = "Z".repeat(44);
    } else {
      const entry = sampleEntry(creds, kind);
      if (!entry) { showErr($("err"), "此模式下该样例不可用。" + (kind === "revoked" ? "请切换公开验证模式。" : "")); return; }
      h = entry.hashed_document;
    }
    $("hashinput").value = h;
    await verifyHash();
  } catch (e) { showErr($("err"), friendlyErr(e.message)); }
}

// ---- batch verify ----
async function verifyBatch() {
  hideErr($("err"));
  const text = $("batchHashes").value.trim();
  if (!text) { showErr($("err"), "请先粘贴一个或多个凭证编号（每行一个，或逗号分隔）。"); return; }
  const hashes = text.split(/[\n,]+/).map((s) => s.trim()).filter(Boolean);
  if (!hashes.length) { showErr($("err"), "批量框中没有找到凭证编号。"); return; }
  const btn = $("batchBtn"); btn.disabled = true; btn.textContent = "验证中…";
  try {
    const data = await api("/api/verify/batch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ hashes }),
    });
    renderBatch(data);
  } catch (e) { showErr($("err"), friendlyErr(e.message)); }
  finally { btn.disabled = false; btn.textContent = "批量验证"; }
}
function renderBatch(data) {
  _lastBatch = data;
  const s = data.summary || {};
  const rows = (data.results || []).map((r) =>
    "<tr><td>" + esc(r.row) + "</td><td class='mono' style='font-size:11px'>" + esc((r.hashed_document || "").slice(0, 16)) + "…</td>" +
    "<td>" + chipFor(r.verdict) + "</td><td>" + esc(r.receipt_id) + "</td><td>" + esc(r.error || r.reason) + "</td></tr>").join("");
  $("batchOut").innerHTML =
    "<p class='hint'><b>汇总 Summary:</b> 共 " + s.total + " · 有效 " + (s.valid || 0) + " · 已注销 " +
    (s.revoked || 0) + " · 查无此证 " + (s.not_found || 0) + " · 无效 " +
    (s.invalid || 0) + " · 出错 " + (s.error || 0) + "</p>" +
    "<div class='tbl-scroll' style='max-height:280px'><table class='tbl'><thead><tr><th>#</th><th>凭证编号</th><th>结果</th><th>收据</th><th>说明</th></tr></thead><tbody>" +
    rows + "</tbody></table></div>";
  $("batchCsvBtn").style.display = "inline-block";
}
function downloadBatchCsv() {
  if (!_lastBatch) return;
  const escq = (s) => '"' + String(s == null ? "" : s).replace(/"/g, '""') + '"';
  const lines = [["row", "hashed_document", "verdict", "receipt_id", "reason", "error"].join(",")];
  (_lastBatch.results || []).forEach((r) => {
    lines.push([r.row, r.hashed_document || "", r.verdict || "", r.receipt_id || "", r.reason || "", r.error || ""].map(escq).join(","));
  });
  const blob = new Blob([lines.join("\n")], { type: "text/csv" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "batch-verify-results.csv";
  a.click();
  URL.revokeObjectURL(a.href);
}

// ---- verify document ----
async function verifyDocument() {
  hideErr($("err"));
  const btn = $("verifyDocBtn");
  btn.disabled = true; btn.textContent = "验证中…";
  try {
    let result;
    if (selectedFile) {
      const fd = new FormData();
      fd.append("file", selectedFile);
      result = await api("/api/verify/document", { method: "POST", body: fd });
    } else {
      const text = $("docjson").value.trim();
      if (!text) { showErr($("err"), "请先选择文件或粘贴凭证 JSON。"); return; }
      let document;
      try { document = JSON.parse(text); } catch (e) { showErr($("err"), "JSON 格式错误：" + e.message); return; }
      result = await api("/api/verify/document", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ document }),
      });
    }
    showVerdict(result, "doc", selectedFile ? null : JSON.parse($("docjson").value.trim() || "{}"));
  } catch (e) { showErr($("err"), friendlyErr(e.message)); }
  finally { btn.disabled = false; btn.textContent = "验证 JSON 文档"; }
}

// ---- verify hash ----
async function verifyHash() {
  hideErr($("err"));
  const h = $("hashinput").value.trim();
  if (!h) { showErr($("err"), "请先粘贴凭证编号。"); return; }
  const btn = $("verifyHashBtn"); btn.disabled = true; btn.textContent = "验证中…";
  try {
    const result = await api("/api/verify/" + encodeURIComponent(h));
    showVerdict(result, "hash", null);
  } catch (e) { showErr($("err"), friendlyErr(e.message)); }
  finally { btn.disabled = false; btn.textContent = "验证"; }
}

// ---- fetch issued PDF by hash ----
async function fetchPdf() {
  const h = $("hashinput").value.trim() || (lastResult && lastResult.hashed_document);
  if (!h) { showErr($("err"), "请先输入凭证编号。"); return; }
  try {
    const res = await fetch("/api/pdf/" + encodeURIComponent(h));
    if (!res.ok) {
      const d = await res.json().catch(() => ({}));
      showErr($("err"), d.detail || "链上无此凭证的 PDF 文件。");
      return;
    }
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "credential-" + h.slice(0, 12) + ".pdf";
    a.click();
    URL.revokeObjectURL(a.href);
  } catch (e) { showErr($("err"), e.message); }
}

// dropzone
const dz = $("dropzone"), dzInput = $("dropfile");
dz.addEventListener("click", () => dzInput.click());
dzInput.addEventListener("change", (e) => {
  const f = e.target.files && e.target.files[0];
  if (!f) return;
  handleFile(f);
});
["dragover", "dragenter"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("hover"); }));
["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("hover"); }));
dz.addEventListener("drop", (e) => {
  const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
  if (f) handleFile(f);
});
function handleFile(f) {
  hideErr($("err"));
  if (f.name.toLowerCase().match(/\.pdf$/)) {
    selectedFile = null;
    $("dropFileName").textContent = "已选择: " + f.name + " (" + (f.size / 1024).toFixed(1) + " KB) —— 正在自动填充…";
    dz.classList.add("hasfile");
    extractPdfInto(f, "docjson", "extractNote").then(() => {
      $("dropFileName").textContent = "已选择: " + f.name + " —— 已自动填充，请核对后验证";
    }).catch(() => {
      $("dropFileName").textContent = "已选择: " + f.name + " —— 自动填充失败";
    });
    return;
  }
  selectedFile = f;
  dz.classList.add("hasfile");
  $("dropFileName").textContent = "已选择: " + f.name + " (" + (f.size / 1024).toFixed(1) + " KB) —— 验证中…";
  if (!f.name.toLowerCase().match(/\.(json|txt)$/)) {
    $("dropFileName").textContent = "已选择: " + f.name + " —— 已开始验证（系统将自动判断文件类型）";
  }
  verifySelectedFile(f);
}
async function verifySelectedFile(f) {
  try {
    const fd = new FormData();
    fd.append("file", f);
    const result = await api("/api/verify/document", { method: "POST", body: fd });
    $("dropFileName").textContent = "已选择: " + f.name + " —— 验证完成";
    let doc = null;
    if (f.name.toLowerCase().endsWith(".json") || f.name.toLowerCase().endsWith(".txt")) {
      try { doc = JSON.parse(await f.text()); } catch (e) { /* keep null */ }
    }
    showVerdict(result, "doc", doc);
  } catch (e) {
    $("dropFileName").textContent = "已选择: " + f.name + " —— 验证失败";
    showErr($("err"), friendlyErr(e.message));
  }
}

// PDF auto-fill: upload a certificate PDF -> fill a JSON textarea with the
// extracted draft. Never auto-submits: the user reviews, then clicks Verify.
async function extractPdfInto(f, targetId, noteId) {
  const note = $(noteId);
  note.className = "extract-note";
  const fill = (mode, doc, conf, warnings, fieldConf) => {
    $(targetId).value = JSON.stringify(doc, null, 2);
    if (targetId === "docjson") {
      const adv = $("advancedCard");
      if (adv) { const d = adv.querySelector("details"); if (d) d.open = true; }
      $("docjson").scrollIntoView({ behavior: "smooth", block: "center" });
    }
    const exact = mode === "embedded_payload";
    note.className = "extract-note on " + (exact ? "ok" : "warn");
    let html = "";
    if (exact) {
      html += '<span class="en-badge">精确提取</span>已从凭证 PDF 内嵌数据提取完整 JSON，置信度 100%。' +
        '<div class="en-acts"><button class="btn sm" onclick="verifyDocFromExtract()">验证凭证 Verify</button></div>';
    } else {
      const pct = Math.round((conf || 0) * 100);
      html += '<span class="en-badge">自动识别</span>已按文本层提取字段，整体置信度 <b>' + pct + '%</b>。' +
        '以下字段仅供参考，请核对后提交：';
      const low = Object.entries(fieldConf || {}).filter(([, c]) => c < 0.95)
        .map(([k, c]) => '<span class="en-field">' + esc(k.split(".").pop()) + " " + Math.round(c * 100) + "%</span>").join("");
      if (low) html += '<div style="margin-top:6px">低置信度：' + low + "</div>";
      // warnings come from the PDF's text layer — attacker-controlled input,
      // so each one is escaped individually before joining.
      if (warnings && warnings.length) html += "<div>" + warnings.slice(0, 4).map(esc).join("；") + "</div>";
      html += '<div class="en-acts"><button class="btn sm" onclick="verifyDocFromExtract()">核对后验证 Verify</button></div>';
    }
    note.innerHTML = html;
  };
  try {
    const fd = new FormData();
    fd.append("file", f);
    const res = await api("/api/extract/pdf", { method: "POST", body: fd });
    fill(res.mode, res.document, res.confidence, res.warnings, res.field_confidence);
  } catch (e) {
    note.className = "extract-note on warn";
    note.innerHTML = "<span class=\"en-badge\">无法自动填充</span>" +
      esc(friendlyErr(e.message)) + " 可改拖 JSON 文件直接验证，或粘贴凭证编号。";
    throw e;
  }
}
function verifyDocFromExtract() { verifyDocument(); }
