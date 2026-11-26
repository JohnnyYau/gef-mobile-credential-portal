// format.js - verdict/label formatting, check rows, receipts, chart
"use strict";

// ---- plain-language verdict mapping ----
const VERDICT_ZH = {
  "VALID": "真實有效", "VALID ON CHAIN": "真實有效", "REVOKED": "已註銷",
  "NOT FOUND": "查無此證", "INVALID": "無效", "CHAIN DATA CORRUPT": "鏈數據損壞"
};
function verdictZh(v) { return VERDICT_ZH[(v || "").toUpperCase()] || v || "—"; }
function verdictEn(v) {
  v = (v || "").toUpperCase();
  if (v === "VALID ON CHAIN") return "VALID";
  return v;
}
function verdictPill(v) {
  v = (v || "").toUpperCase();
  const zh = verdictZh(v);
  if (v === "VALID" || v === "VALID ON CHAIN") return '<span class="tag-pill ok">' + esc(zh) + "</span>";
  if (v === "REVOKED") return '<span class="tag-pill warn">' + esc(zh) + "</span>";
  if (v === "NOT FOUND") return '<span class="tag-pill neu">' + esc(zh) + "</span>";
  return '<span class="tag-pill bad">' + esc(zh) + "</span>";
}

// ---- friendly error messages ----
function friendlyErr(msg) {
  msg = msg || "";
  const m = msg.toLowerCase();
  if (m.includes("pdf") && (m.includes("reject") || m.includes("not")) && m.includes("upload"))
    return "這份 PDF 不是本系統簽發的憑證。請上傳本系統簽發的 PDF（內含驗證數據），或改用憑證編號驗證。";
  if (m.includes("too large") || m.includes("413"))
    return "文件太大了（上限 5 MB）。請壓縮後重試。";
  if (m.includes("hash must") || m.includes("422"))
    return "憑證編號格式不對。請粘貼完整的 44 位憑證編號。";
  if (m.includes("rate limit"))
    return "操作太頻繁了，請稍等片刻再試。";
  if (m.includes("public verifier") || m.includes("403"))
    return "該功能已在此公開實例禁用。";
  return msg;
}

const CHECK_META = [
  ["chain_integrity", "1. 鏈完整性 Chain integrity"],
  ["signer_trusted", "2. 簽發方可信 Signer trusted"],
  ["on_chain_record", "3. 鏈上存在記錄 On-chain record"],
  ["hash_match", "4. 文件與鏈上記錄一致 Hash match"],
  ["signature_valid", "5. 簽名有效 Signature valid"],
  ["not_revoked", "6. 未被註銷 Not revoked"],
];

function renderChecks(result) {
  const rows = CHECK_META.map(([key, label]) => {
    const val = result[key];
    let chip;
    if (val === true) chip = '<span class="chip pass">通過 PASS</span>';
    else if (val === false) chip = '<span class="chip fail">未通過 FAIL</span>';
    else chip = '<span class="chip na">不適用 N/A</span>';
    return '<tr><th>' + label + '</th><td>' + chip + '</td></tr>';
  }).join("");
  $("checksTable") && ($("checksTable").innerHTML = rows);
  $("hashValue").textContent = result.hashed_document || "";
}

function renderHolder(doc) {
  const el = $("holderCard");
  if (!doc || typeof doc !== "object") { el.classList.remove("show"); return; }
  const pp = doc.PersonalParticulars || {}, ai = doc.AcademicInfo || {}, di = doc.DocumentInfo || {};
  const rows = [
    ["姓名 Name", [pp.Surname, pp.GivenNames].filter(Boolean).join(" ")],
    ["學號 Student ID", pp.StudentID],
    ["學位 Degree", ai.DegreeName],
    ["院系 Org / Unit", [di.IssuingO, di.IssuingOU].filter(Boolean).join(" / ")],
    ["類型 Type", di.DocType],
    ["簽發日期 Issued", di.DateOfIssue],
  ].filter(r => r[1] !== undefined && r[1] !== null && String(r[1]).trim() !== "");
  $("holderTable").innerHTML = rows.map(r =>
    "<tr><td>" + esc(r[0]) + "</td><td>" + esc(r[1]) + "</td></tr>").join("");
  el.classList.add("show");
}

function showVerdict(result, kind, doc) {
  const el = $("verdict");
  const text = result.verdict || "INVALID";
  const up = text.toUpperCase();
  let cls = "invalid", ico = "✕";
  const good = kind === "hash" ? up === "VALID ON CHAIN" : up === "VALID";
  if (good) { cls = "valid"; ico = "✓"; }
  else if (up === "REVOKED") { cls = "revoked"; ico = "↩"; }
  else if (up === "NOT FOUND") { cls = "notfound"; ico = "?"; }
  else if (up === "CHAIN DATA CORRUPT") { cls = "corrupt"; ico = "!"; }
  el.className = "verdict show " + cls;
  $("verdictIco").textContent = ico;
  $("verdictText").textContent = verdictZh(text);
  $("verdictEn").textContent = "(" + verdictEn(text) + ")";
  lastResult = result;
  const hasHash = !!(result && (result.hashed_document || result.receipt_id));
  $("receiptBtn").style.display = hasHash ? "inline-block" : "none";
  $("printReceiptBtn").style.display = hasHash ? "inline-block" : "none";
  $("qrBtn").style.display = result && result.hashed_document ? "inline-block" : "none";
  $("pdfFetchBtn").style.display = result && result.hashed_document ? "inline-block" : "none";
  renderChecks(result);
  renderHolder(doc || null);
  const note = $("verdictNote");
  if (result.chain_error) {
    note.textContent = "鏈數據問題：請管理員恢復鏈備份。" + result.chain_error;
  } else if (kind === "hash" && result.hash_match === null) {
    note.textContent = "第 4 項需要完整文檔——如持有 PDF/JSON，請拖入上方進行完整 6 項驗證。";
  } else if (result.status && result.status.issue_heights) {
    note.textContent = "簽發區塊: " + (result.status.issue_heights.join(", ") || "無") +
      " · 註銷區塊: " + (result.status.revoke_heights.join(", ") || "無") +
      (result.reason ? " · 註銷原因: " + result.reason : "") +
      (result.effective_at ? " · 生效時間: " + new Date(result.effective_at * 1000).toLocaleString() : "");
  } else {
    note.textContent = "";
  }
}

function chipFor(verdict) {
  const up = (verdict || "").toUpperCase();
  const zh = verdictZh(up);
  if (up === "VALID ON CHAIN") return '<span class="chip pass">' + esc(zh) + "</span>";
  if (up === "REVOKED") return '<span class="chip fail">' + esc(zh) + "</span>";
  if (up === "NOT FOUND") return '<span class="chip na">' + esc(zh) + "</span>";
  return '<span class="chip na">' + esc(zh || verdict || "—") + "</span>";
}

// ---- downloadable verification receipt ----
function receiptHtml(result) {
  const now = new Date().toISOString().replace("T", " ").slice(0, 19) + " UTC";
  const hid = result.hashed_document || "";
  const checks = CHECK_META.map(([key, label]) =>
    "<tr><td>" + label + "</td><td>" + (result[key] === true ? "PASS" : result[key] === false ? "FAIL" : "N/A") + "</td></tr>").join("");
  const url = (window.__version && window.__version.public_base_url) || location.origin;
  const ver = window.__version ? window.__version.app + " v" + window.__version.version : "Gef26 verifier";
  const chainInfo = window.__version && window.__version.chain;
  return "<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'><title>驗證報告 Verification receipt</title>" +
    "<style>body{font-family:system-ui,'Segoe UI','Microsoft YaHei',Arial,sans-serif;max-width:640px;margin:32px auto;padding:0 16px;color:#1a1d21}h1{font-size:20px;margin-bottom:2px}.muted{color:#667085;font-size:12px}table{width:100%;border-collapse:collapse;margin:16px 0}th,td{text-align:left;padding:8px;border-bottom:1px solid #e4e7ec;font-size:13px}th{color:#667085;font-weight:600}.ok{color:#067647}.box{border:1px solid #e4e7ec;border-radius:10px;padding:14px;margin-top:14px;font-size:13px}.disc{font-size:11px;color:#667085;margin-top:18px;line-height:1.5}.mono{font-family:ui-monospace,Consolas,monospace;font-size:11px;word-break:break-all}</style></head><body>" +
    "<h1>驗證報告 Verification receipt</h1><p class='muted'>由 " + esc(url) + " 生成</p>" +
    "<div class='box'><span class='ok'><b>" + esc(verdictZh(result.verdict)) + " (" + esc(verdictEn(result.verdict)) + ")</b></span></div>" +
    "<table>" + checks + "</table>" +
    "<div class='box'><b>收據編號 Receipt ID:</b> <span class='mono'>" + (esc(result.receipt_id) || "—") + "</span><br>" +
    "<b>憑證編號 Credential hash:</b> <span class='mono'>" + esc(hid) + "</span><br>" +
    "<b>驗證時間 Verified at:</b> " + esc(now) + "<br>" +
    "<b>驗證器 Verifier:</b> " + esc(ver) + "<br>" +
    "<b>鏈 Chain:</b> " + esc(chainInfo ? chainInfo.name + " @ height " + chainInfo.height : "—") + "</div>" +
    "<p class='disc'>“真實有效”表示在此時刻，6 項檢查均通過；本報告不構成法律認證。報告中不含出生日期等隱私信息。</p>" +
    "</body></html>";
}
function downloadReceipt(result) {
  const blob = new Blob([receiptHtml(result || lastResult)], { type: "text/html" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "verification-receipt.html";
  a.click();
  URL.revokeObjectURL(a.href);
}
function printReceipt(result) {
  const w = window.open("", "_blank");
  if (!w) return;
  w.document.write(receiptHtml(result || lastResult));
  w.document.close();
  w.focus();
  w.print();
}

// ---- QR ----
function setQr(imgId, hash) {
  const img = $(imgId);
  img.src = "/api/qr/" + encodeURIComponent(hash);
  img.style.display = "inline-block";
}
$("qrBtn").addEventListener("click", () => {
  const h = $("hashinput").value.trim() || (lastResult && lastResult.hashed_document);
  if (!h) { showErr($("err"), "請先輸入憑證編號。"); return; }
  hideErr($("err"));
  setQr("qrImg", h);
  $("qrLink").textContent = "掃碼將打開: " + location.origin + "/verify?hash=" + h.slice(0, 20) + "…";
});
// The issue panel lives in the staff console only (U12 R1), so this control is
// optional on the public page.
const issueQrBtnEl = $("issueQrBtn");
if (issueQrBtnEl) issueQrBtnEl.addEventListener("click", () => {
  if (!lastIssuedHash) return;
  setQr("issueQrImg", lastIssuedHash);
});

function renderHourlyChart(hours) {
  const max = Math.max(1, ...hours.map((h) => h.count));
  const chartW = 700, padL = 30, padT = 26, padB = 6, hpx = 100;
  const barW = Math.max(6, Math.floor((chartW - padL) / Math.max(1, hours.length)) - 5);
  const bars = hours.map((h, i) => {
    const bh = Math.max(2, Math.round((h.count / max) * hpx));
    const label = new Date(h.hour * 3600 * 1000).toLocaleTimeString([], { hour: "2-digit" });
    return '<rect x="' + (padL + i * (barW + 5)) + '" y="' + (padT + hpx - bh) + '" width="' + barW +
      '" height="' + bh + '" fill="#0f766e" rx="2"><title>' + esc(label) + ": " + h.count +
      " issues</title></rect>";
  }).join("");
  $("anomalyChart").innerHTML = '<svg width="100%" viewBox="0 0 ' + chartW + ' 150" style="display:block;margin-top:10px">' +
    '<text x="' + padL + '" y="16" font-size="12" fill="#5b6b7b">每小時簽發量（最近 24 小時）</text>' +
    '<line x1="' + padL + '" y1="' + (padT + hpx + 1) + '" x2="' + (chartW - 8) + '" y2="' + (padT + hpx + 1) +
    '" stroke="#dfe5ec" stroke-width="1"/>' + bars + '</svg>';
}
