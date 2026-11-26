// registrar.js - issue/revoke, API keys, CSV batch wizard, signers, maker
"use strict";

// ---- API keys (admin) ----
async function createApikey() {
  hideErr($("apikeyErr"));
  const name = $("apikeyName").value.trim() || "unnamed";
  const btn = $("apikeyCreateBtn"); btn.disabled = true;
  try {
    const res = await api("/api/admin/apikeys", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    $("apikeyOk").textContent = "创建成功。立即复制密钥——只显示一次：\n" + res.key;
    $("apikeyOk").style.display = "block";
    $("apikeyName").value = "";
    await loadApikeys();
  } catch (e) { showErr($("apikeyErr"), friendlyErr(e.message)); }
  finally { btn.disabled = false; }
}
async function loadApikeys() {
  try {
    const data = await api("/api/admin/apikeys");
    const rows = (data.keys || []).map((k) =>
      "<tr><td>" + esc(k.name) + "</td><td class='mono' style='font-size:11px'>" + esc(k.id) + "</td><td>" + (k.revoked ? "已撤销" : "使用中") + "</td>" +
      "<td><button class='btn ghost sm' data-revoke='" + esc(k.id) + "'>撤销</button></td></tr>").join("");
    $("apikeyTable").innerHTML = "<thead><tr><th>名称</th><th>ID</th><th>状态</th><th></th></tr></thead><tbody>" + rows + "</tbody>";
  } catch (e) { /* admin disabled in public mode */ }
}

// ---- batch issue wizard (admin) ----
const CSV_ALIASES = {
  "surname": ["surname", "姓", "lastname", "familyname"],
  "given_names": ["given_names", "givennames", "名", "firstname"],
  "sex": ["sex", "性别"],
  "dob": ["dob", "出生日期", "birthdate", "birth"],
  "student_id": ["student_id", "studentid", "学号", "id"],
  "degree": ["degree", "degreename", "学位", "专业", "program"],
  "start": ["start", "degreestartdate", "开始日期"],
  "end": ["end", "degreeenddate", "结束日期"],
  "honour": ["honour", "荣誉"],
  "observations": ["observations", "备注", "note"],
  "issuer": ["issuer", "issuingo", "签发机构"],
  "ou": ["ou", "issuingou", "院系"],
  "doc_type": ["doc_type", "doctype", "类型"],
  "signature": ["signature", "authorizedsignature", "签发人"],
  "date_of_issue": ["date_of_issue", "dateofissue", "签发日期"],
  "email": ["email", "邮箱", "student_email"],
};
function parseCsv(text) {
  // minimal RFC-4180-ish parser: handles quoted fields with commas/escaped quotes
  const rows = [];
  let row = [], cur = "", inQ = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (inQ) {
      if (ch === '"') { if (text[i + 1] === '"') { cur += '"'; i++; } else inQ = false; }
      else cur += ch;
    } else if (ch === '"') { inQ = true; }
    else if (ch === ",") { row.push(cur); cur = ""; }
    else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && text[i + 1] === "\n") i++;
      row.push(cur); cur = "";
      if (row.some((c) => c.trim() !== "")) rows.push(row);
      row = [];
    } else cur += ch;
  }
  row.push(cur);
  if (row.some((c) => c.trim() !== "")) rows.push(row);
  return rows;
}
function mapHeaders(headerRow) {
  const map = {};
  headerRow.forEach((h, i) => {
    const key = (h || "").trim().toLowerCase().replace(/[\s-]/g, "_");
    for (const field in CSV_ALIASES) {
      if (CSV_ALIASES[field].includes(key)) { map[i] = field; break; }
    }
  });
  return map;
}
function csvToCredentials(text, orgDefault) {
  const rows = parseCsv(text);
  if (rows.length < 2) throw new Error("CSV 至少需要表头 + 1 行数据。");
  const map = mapHeaders(rows[0]);
  const today = new Date().toISOString().slice(0, 10).replace(/-/g, "");
  const out = [];
  const seen = new Set();
  rows.slice(1).forEach((cells, idx) => {
    const g = (field) => { const i = Object.keys(map).find((k) => map[k] === field); return i === undefined ? "" : (cells[+i] || "").trim(); };
    const surname = g("surname"), given = g("given_names"), sid = g("student_id"), dob = g("dob");
    if (!surname && !given && !sid) { out.push({ row: idx + 2, error: "缺少姓名/学号" }); return; }
    const doc = {
      PersonalParticulars: {
        Surname: surname || "UNKNOWN", GivenNames: given || "STUDENT",
        Sex: g("sex") || "X", DOB: dob || "19000101", StudentID: sid || ("B" + String(idx + 1).padStart(7, "0")),
      },
      AcademicInfo: {
        DegreeName: g("degree") || "Credential", DegreeStartDate: g("start") || "20220901",
        DegreeEndDate: g("end") || "20260801", Honour: g("honour") || "NO HONOUR",
        Observations: g("observations") || "NO OFFICIAL OBSERVATIONS",
      },
      DocumentInfo: {
        DateOfIssue: g("date_of_issue") || today,
        AuthorizedSignature: g("signature") || "REGISTRAR",
        IssuingO: g("issuer") || orgDefault || "UNIVERSITY OF UTOPIA",
        IssuingOU: g("ou") || "RECORD OFFICE",
        DocType: g("doc_type") || "CERTIFICATE OF DIPLOMA",
      },
    };
    // U12 R4: an e-mail column in the CSV is no longer forwarded. The server
    // ignores request-supplied recipients; NOTIFY_TO decides who gets mail.
    const item = { document: doc };
    const key = [surname, given, sid, dob].join("|");
    if (seen.has(key)) { out.push({ row: idx + 2, error: "重复行：" + key, dup: true }); return; }
    seen.add(key);
    out.push({ row: idx + 2, item });
  });
  return out;
}
function downloadText(name, text, type) {
  const blob = new Blob([text], { type: type || "text/plain" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}
function downloadTemplate() {
  downloadText("credentials-template.csv",
    "surname,given_names,sex,dob,student_id,degree,start,end,honour,email\n" +
    "CHAN,TAI MAN,M,19880808,22000000,Bachelor of Engineering / Electronic and Electrical Engineering,20220815,20260801,1ST HON,student@example.com\n" +
    "NG,KA LOK,F,19991212,22000001,Bachelor of Science in Computing,20220901,20260601,2ND HON,\n",
    "text/csv");
}
let _previewRows = null;
// U13 F5: the batch result of the last run, kept so "export all holder links"
// does not have to re-issue anything or re-read the DOM.
let _lastIssueBatch = [];

function holderAbs(path) {
  const base = (window.__version && window.__version.public_base_url) || location.origin;
  return String(base).replace(/\/$/, "") + path;
}

function downloadHolderLinksCsv() {
  const rows = [["row", "student_id", "hashed_document", "holder_url"]];
  (_lastIssueBatch || []).forEach((r) => {
    if (!r.ok) return;
    rows.push([r.row, r.student_id || "", r.hashed_document || "",
               r.holder_path ? holderAbs(r.holder_path) : ""]);
  });
  if (rows.length === 1) return;
  const csv = rows.map((cols) =>
    cols.map((v) => '"' + String(v == null ? "" : v).replace(/"/g, '""') + '"').join(",")
  ).join("\r\n");
  downloadText("holder-links.csv", csv, "text/csv");
}

(function wireBatchOut() {
  const out = document.getElementById("batchRegOut");
  if (!out) return;
  out.addEventListener("click", (ev) => {
    const btn = ev.target.closest ? ev.target.closest("[data-holder], [data-batch-links]") : null;
    if (!btn) return;
    if (btn.hasAttribute("data-batch-links")) { downloadHolderLinksCsv(); return; }
    const url = holderAbs(btn.getAttribute("data-holder"));
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(url);
      const old = btn.textContent;
      btn.textContent = "已复制";
      setTimeout(() => { btn.textContent = old; }, 1500);
    } else {
      window.prompt("持证人链接", url);
    }
  });
})();
function previewBatch() {
  hideErr($("batchRegErr"));
  const text = $("batchRegText").value.trim();
  const file = $("batchRegCsv").files && $("batchRegCsv").files[0];
  if (!text && !file) { showErr($("batchRegErr"), "请上传 CSV 文件或粘贴 CSV 内容。"); return; }
  const org = $("batchOrg").value.trim();
  let rows;
  try {
    rows = csvToCredentials(text || "", org);
  } catch (e) { showErr($("batchRegErr"), e.message); return; }
  _previewRows = rows;
  const okRows = rows.filter((r) => r.item);
  const badRows = rows.filter((r) => r.error);
  const head = "<p class='hint'><b>预览 Preview:</b> 共 " + rows.length + " 行 · 可签发 " + okRows.length + " · 有问题 " + badRows.length + "</p>";
  const table = okRows.slice(0, 8).map((r) => {
    const pp = r.item.document.PersonalParticulars, ai = r.item.document.AcademicInfo;
    return "<tr><td>" + esc(r.row) + "</td><td>" + esc(pp.Surname + " " + pp.GivenNames) + "</td><td>" + esc(pp.StudentID) + "</td>" +
      "<td>" + esc(ai.DegreeName) + "</td><td>" + esc(r.item.document.DocumentInfo.IssuingO) + "</td></tr>";
  }).join("");
  const bad = badRows.slice(0, 5).map((r) => "<div class='note'>第 " + esc(r.row) + " 行：" + esc(r.error) + "</div>").join("");
  $("batchRegPreview").innerHTML = head +
    (okRows.length ? "<div class='tbl-scroll' style='max-height:220px'><table class='tbl'><thead><tr><th>行</th><th>姓名</th><th>学号</th><th>学位</th><th>签发机构</th></tr></thead><tbody>" + table + "</tbody></table>" +
    (okRows.length > 8 ? "<div class='note'>… 仅显示前 8 行</div>" : "") + "</div>" : "") + bad;
  $("batchRegBtn").textContent = "签发 " + okRows.length + " 份 Issue";
  $("batchRegBtn").disabled = okRows.length === 0;
}
async function runBatchIssue() {
  if (!_previewRows) return;
  const items = _previewRows.filter((r) => r.item).map((r) => r.item);
  const btn = $("batchRegBtn"); btn.disabled = true;
  const prog = $("batchRegProgress"); prog.style.display = "block";
  $("batchRegFill").style.width = "0%";
  hideErr($("batchRegErr")); $("batchRegOk").style.display = "none";
  try {
    const data = await api("/api/issue/batch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ credentials: items }),
    });
    $("batchRegFill").style.width = "100%";
    const s = data.summary || {};
    _lastIssueBatch = data.results || [];
    const rows = (data.results || []).map((r) => {
      const pdf = r.credential_pdf_url || r.pdf_url;
      const cell = r.ok
        ? '<span class="tag-pill ok">成功</span> <a class="btn ghost sm" style="text-decoration:none" href="' + esc(pdf) + '" download>PDF</a> <a class="btn ghost sm" style="text-decoration:none" href="' + esc(r.qr_url) + '">QR</a>' +
          (r.holder_path ? ' <button class="btn ghost sm" data-holder="' + esc(r.holder_path) + '">持证人链接</button>' : '')
        : '<span class="tag-pill bad">失败</span> ' + esc(r.error || "");
      return "<tr><td>" + esc(r.row) + "</td><td class='mono' style='font-size:11px'>" + esc((r.hashed_document || "").slice(0, 16)) + "…</td>" + "<td>" + cell + "</td></tr>";
    }).join("");
    $("batchRegOut").innerHTML = "<p class='hint'><b>签发结果:</b> 共 " + s.total + " · 成功 " + s.ok + " · 失败 " + s.failed + "</p>" +
      "<div class='tbl-scroll' style='max-height:300px'><table class='tbl'><thead><tr><th>行</th><th>凭证编号</th><th>结果</th></tr></thead><tbody>" + rows + "</tbody></table></div>" +
      (s.ok ? "<div class='row'><button class='btn ghost sm' data-batch-links='1'>导出全部持证人链接 CSV</button></div>" : "");
    if (s.ok) {
      $("batchRegOk").textContent = "已成功签发 " + s.ok + " 份凭证到链上。逐个下载 PDF（完整凭证）/ QR，复制持证人链接，或导出全部链接 CSV。";
      $("batchRegOk").style.display = "block";
      refreshHealth();
    }
  } catch (e) {
    showErr($("batchRegErr"), friendlyErr(e.message));
    $("batchRegFill").style.width = "0%";
  } finally {
    btn.disabled = false;
    prog.style.display = "none";
  }
}

// ---- issue one ----
async function issueDoc() {
  hideErr($("issueErr"));
  const text = $("issuejson").value.trim();
  if (!text) { showErr($("issueErr"), "请先粘贴凭证 JSON。"); return; }
  let document;
  try { document = JSON.parse(text); } catch (e) { showErr($("issueErr"), "JSON 格式错误：" + e.message); return; }
  const btn = $("issueBtn"); btn.disabled = true; btn.textContent = "签发中…";
  try {
    // U12 R4: no recipient field is sent. The server records the event and
    // sends only to its configured NOTIFY_TO.
    const body = { document };
    const res = await api("/api/issue", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    lastIssuedHash = res.hashed_document;
    let msg = "已在高度 " + res.height + " 签发。凭证编号：" + res.hashed_document;
    if (res.notification && res.notification.status !== "skipped") {
      msg += " · 邮件: " + res.notification.status + (res.notification.detail ? " (" + res.notification.detail + ")" : "");
    }
    $("issueOk").textContent = msg;
    $("issueOk").style.display = "block";
    $("issueQrRow").style.display = "flex";
    $("issueQrImg").style.display = "none";
    $("issuePdfLink").href = res.pdf_url;
    $("revokehash").value = res.hashed_document;
    $("hashinput").value = res.hashed_document;
    refreshHealth();
  } catch (e) { showErr($("issueErr"), friendlyErr(e.message)); }
  finally { btn.disabled = false; btn.textContent = "签发上链"; }
}

// ---- revoke ----
async function revokeDoc() {
  hideErr($("revokeErr"));
  const h = $("revokehash").value.trim();
  if (!h) { showErr($("revokeErr"), "请输入要注销的凭证编号。"); return; }
  if (!confirm("确认注销 " + h.slice(0, 24) + "…？此操作只追加、不可撤销。")) return;
  const btn = $("revokeBtn"); btn.disabled = true; btn.textContent = "注销中…";
  try {
    const reason = $("revokeReason").value.trim() || undefined;
    const effRaw = $("revokeEffective").value.trim();
    const effectiveAt = effRaw ? Number(effRaw) : undefined;
    const res = await api("/api/revoke", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ hashed_document: h, reason: reason, effective_at: effectiveAt }),
    });
    $("revokeOk").textContent = "已在高度 " + res.height + " 注销。可重新验证确认。";
    $("revokeOk").style.display = "block";
    refreshHealth();
  } catch (e) { showErr($("revokeErr"), friendlyErr(e.message)); }
  finally { btn.disabled = false; btn.textContent = "注销"; }
}

// ---- signers ----
async function loadSigners() {
  try {
    const r = await api("/api/signers");
    const rows = r.signers.map((s) => {
      const isActive = s.sha256fgpt === r.active;
      const retired = s.retired_at_height;
      // U16: a retired key stays in the registry so its old blocks keep
      // verifying; it just cannot issue or be made active again.
      const state = (isActive ? ' <span class="tag-pill ok">激活中</span>' : "") +
        (retired != null ? ' <span class="tag-pill warn">退役于块 #' + esc(String(retired)) + '</span>' : "");
      const actions = (isActive || retired != null) ? "" :
        '<button class="btn ghost sm" data-fp="' + esc(s.sha256fgpt) + '">设为激活</button> ' +
        '<button class="btn ghost sm" data-retire="' + esc(s.sha256fgpt) + '">退役</button>';
      return "<tr><td>" + esc(s.name) + state +
        "</td><td class=\"mono\">" + esc(s.ds_algo) + "</td>" +
        "<td class=\"mono\">" + esc(s.sha256fgpt.slice(0, 20)) + "…</td>" +
        "<td>" + actions + "</td></tr>";
    }).join("");
    $("signersTable").innerHTML = "<tr><th>名称</th><th>算法</th><th>指纹</th><th></th></tr>" + rows;
    $("signersTable").querySelectorAll("button[data-fp]").forEach((b) => {
      b.addEventListener("click", () => setActiveSigner(b.dataset.fp));
    });
    $("signersTable").querySelectorAll("button[data-retire]").forEach((b) => {
      b.addEventListener("click", () => retireSigner(b.dataset.retire));
    });
  } catch (e) {
    $("signersTable").innerHTML = "<tr><td colspan=4>" + esc(friendlyErr(e.message)) + "</td></tr>";
  }
}
async function retireSigner(fp) {
  hideErr($("signerErr"));
  if (!confirm("退役该签发方？它签署过的历史块仍然有效，之后不再被信任；重新注册同一把公钥可以恢复信任。")) return;
  try {
    const r = await api("/api/signers/retire", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sha256fgpt: fp }),
    });
    $("signerOk").textContent = "已退役，信任边界为块 #" + r.retired_at_height +
      "；此前签署的块仍然有效。";
    $("signerOk").style.display = "block";
    loadSigners(); refreshHealth();
  } catch (e) { showErr($("signerErr"), friendlyErr(e.message)); }
}
async function setActiveSigner(fp) {
  hideErr($("signerErr"));
  try {
    await api("/api/signers/active", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sha256fgpt: fp }),
    });
    $("signerOk").textContent = "已切换激活签发方。";
    $("signerOk").style.display = "block";
    loadSigners(); refreshHealth();
  } catch (e) { showErr($("signerErr"), friendlyErr(e.message)); }
}
async function addSigner() {
  hideErr($("signerErr"));
  const name = $("signerName").value.trim();
  const algo = $("signerAlgo").value;
  const btn = $("addSignerBtn"); btn.disabled = true; btn.textContent = "生成密钥中…";
  try {
    const s = await api("/api/signers", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, ds_algo: algo }),
    });
    $("signerOk").textContent = "已注册 " + s.name + " (" + s.ds_algo + ") — 指纹 " + s.sha256fgpt.slice(0, 20) + "…";
    $("signerOk").style.display = "block";
    $("signerName").value = "";
    loadSigners(); refreshHealth();
  } catch (e) { showErr($("signerErr"), friendlyErr(e.message)); }
  finally { btn.disabled = false; btn.textContent = "注册签发方"; }
}

// ---- self-service credential maker (round 10) ----
function customFields() {
  const v = (id) => $(id).value.trim();
  return {
    surname: v("csSurname"), given_names: v("csGiven"), student_id: v("csStudentId"),
    dob: v("csDob"), sex: v("csSex"), degree: v("csDegree"),
    degree_start: v("csDStart"), degree_end: v("csDEnd"), honour: v("csHonour"),
    observations: v("csObs"), issuer: v("csIssuer"), issuer_unit: v("csUnit"),
  };
}
function clearCustom() {
  $("customOk").textContent = ""; $("customErr").textContent = "";
  $("customResult").style.display = "none";
}
function showCustomResult(r) {
  clearCustom();
  const box = $("customResult");
  const validBadge = r.on_chain
    ? '<span class="badge ok" style="font-weight:700">已上链 · 上传即可验证为真实有效</span>'
    : '<span class="badge" style="background:#fff7e0;border-color:#f0c36d;color:#7a5b12">草稿 · 尚未上链（验证将显示查无此证）</span>';
  box.innerHTML =
    '<div style="margin:10px 0 6px">' + validBadge + '</div>' +
    '<div class="kv">凭证哈希 Hash：<code>' + esc(r.hashed_document) + '</code></div>' +
    (r.height ? '<div class="kv">链上高度 Height：' + esc(r.height) + '</div>' : "") +
    '<div class="kv">保存位置：<code>' + esc(r.output_dir) + '</code></div>' +
    '<div class="row" style="margin-top:10px">' +
    '<a class="btn" href="' + esc(r.pdf_url) + '" download="' + esc(r.file_id) + '.pdf">下载定制 PDF</a>' +
    '<a class="btn ghost" href="' + esc(r.json_url) + '" download="' + esc(r.file_id) + '.json">下载 JSON</a>' +
    '<a class="btn ghost" href="' + esc(r.verify_url) + '">立即验证此凭证</a>' +
    '</div>' +
    '<p class="hint" style="margin-top:8px">上传 PDF 到「验证」页，或点「立即验证」：直接给出真实有效判定。</p>';
  box.style.display = "block";
  loadCustomList();
}
async function buildCustom(issue) {
  clearCustom();
  const btn = issue ? $("customBuildBtn") : $("customDraftBtn");
  const prev = btn.textContent;
  btn.disabled = true; btn.textContent = issue ? "生成签发中…" : "生成中…";
  try {
    const r = await api("/api/custom/build", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(Object.assign(customFields(), { issue })),
    });
    showCustomResult(r);
  } catch (e) { $("customErr").textContent = e.message || String(e); }
  finally { btn.disabled = false; btn.textContent = prev; }
}
async function loadCustomList() {
  try {
    const r = await api("/api/custom/list");
    const dir = $("customOutDir");
    if (dir) dir.textContent = r.output_dir || "";
    const t = $("customTable");
    if (!t) return;
    if (!r.files || !r.files.length) { t.innerHTML = '<tr><td class="muted">还没有生成过凭证——用上面的表单生成第一份。</td></tr>'; return; }
    t.innerHTML =
      "<tr><th>文件</th><th>PDF</th><th>JSON</th></tr>" +
      r.files.map((f) =>
        "<tr><td><code>" + esc(f.name) + "</code></td>" +
        '<td><a class="btn ghost sm" href="' + esc(f.pdf_url) + '" download="' + esc(f.name) + '.pdf">下载</a></td>' +
        '<td><a class="btn ghost sm" href="' + esc(f.json_url) + '" download="' + esc(f.name) + '.json">下载</a></td></tr>'
      ).join("");
  } catch (e) { /* tab may be hidden in public mode */ }
}
$("customBuildBtn").addEventListener("click", () => buildCustom(true));
$("customDraftBtn").addEventListener("click", () => buildCustom(false));
