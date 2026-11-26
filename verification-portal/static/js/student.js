// student.js - holder entry, plus staff-side link minting (U12 R3)
//
// The old flow accepted StudentID + DOB against /api/student/{id}. That endpoint
// is gone: it was enumerable and had no token and no rate limit. A holder link
// is the replacement — signed, scoped to one credential, expiring, and only
// the issuer can mint it.
"use strict";

function holderTokenFrom(raw) {
  const s = String(raw || "").trim();
  if (!s) return "";
  const m = s.match(/\/me\/([A-Za-z0-9._~-]+)/);
  if (m) return m[1];
  if (/^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/.test(s)) return s;
  return "";
}

function openHolder() {
  const err = $("holderErr2");
  if (err) hideErr(err);
  const input = $("holderlink");
  const token = holderTokenFrom(input ? input.value : "");
  if (!token) {
    if (err) showErr(err, "这不像一条持证人链接。请粘贴以 /me/ 开头的地址，或直接粘贴 token。");
    return;
  }
  location.href = "/me/" + encodeURIComponent(token);
}

async function mintHolderLink() {
  const err = $("mintErr");
  const ok = $("mintOk");
  if (err) hideErr(err);
  if (ok) ok.style.display = "none";
  const sid = ($("linkSid") || {}).value ? $("linkSid").value.trim() : "";
  const hash = ($("linkHash") || {}).value ? $("linkHash").value.trim() : "";
  if (!sid || !hash) {
    if (err) showErr(err, "填学号与凭证哈希（签发结果里那串 HashedDocument）。");
    return;
  }
  const btn = $("mintLinkBtn");
  if (btn) { btn.disabled = true; btn.textContent = "生成中…"; }
  try {
    const r = await api("/api/holder-link?student_id=" + encodeURIComponent(sid) +
                        "&hashed_document=" + encodeURIComponent(hash));
    const url = location.origin + r.path;
    if (ok) {
      ok.innerHTML = "链接已生成，复制发给学生：<br><span class=\"mono\">" + esc(url) + "</span>";
      ok.style.display = "block";
    }
    if (hash && $("holderlink")) $("holderlink").value = url;
  } catch (e) {
    if (err) showErr(err, friendlyErr(e.message));
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "生成链接"; }
  }
}
