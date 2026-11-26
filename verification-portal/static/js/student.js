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
    if (err) showErr(err, "這不像一條持證人連結。請粘貼以 /me/ 開頭的地址，或直接粘貼 token。");
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
    if (err) showErr(err, "填學號與憑證哈希（簽發結果裡那串 HashedDocument）。");
    return;
  }
  const btn = $("mintLinkBtn");
  if (btn) { btn.disabled = true; btn.textContent = "生成中…"; }
  try {
    const r = await api("/api/holder-link?student_id=" + encodeURIComponent(sid) +
                        "&hashed_document=" + encodeURIComponent(hash));
    const url = location.origin + r.path;
    if (ok) {
      ok.innerHTML = "連結已生成，複製發給學生：<br><span class=\"mono\">" + esc(url) + "</span>";
      ok.style.display = "block";
    }
    if (hash && $("holderlink")) $("holderlink").value = url;
  } catch (e) {
    if (err) showErr(err, friendlyErr(e.message));
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "生成連結"; }
  }
}
