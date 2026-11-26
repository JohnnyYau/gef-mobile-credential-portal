// log.js - public verification log, anomaly watch, notifications
"use strict";

// ---- public log + anomaly watch ----
async function loadLog() {
  try {
    const d = await api("/api/log");
    const vrows = (d.verifications || []).slice().reverse().map((v) =>
      "<tr><td>" + esc(new Date(v.time * 1000).toLocaleTimeString()) + "</td>" +
      "<td class=\"mono\">" + esc(v.hash_prefix) + "…</td>" +
      "<td>" + verdictPill(v.verdict) + "</td></tr>"
    ).join("");
    $("logTable").innerHTML = "<tr><th>時間</th><th>哈希前綴</th><th>結果</th></tr>" +
      (vrows || "<tr><td colspan=3>暫無驗證記錄 —— 去“驗證”頁試試。</td></tr>");
    const crows = (d.chain_events || []).map((b) =>
      "<tr><td>" + esc(b.height) + "</td><td>" + esc(b.action || "") + "</td>" +
      "<td class=\"mono\">" + esc(b.hash_prefix || "—") + "</td></tr>"
    ).join("");
    $("chainTable").innerHTML = "<tr><th>高度</th><th>操作</th><th>哈希前綴</th></tr>" + crows;
    $("statVerifs").textContent = d.total_verifications || 0;
  } catch (e) {
    $("logTable").innerHTML = "<tr><td colspan=3>" + esc(e.message) + "</td></tr>";
  }
}
async function loadAnomalies() {
  try {
    const d = await api("/api/anomalies");
    const box = $("anomalyBox");
    const methodTag = '<span class="tag-pill ' + (d.method === "isolation_forest" ? "ok" : "neu") + '">' + esc(d.method) + "</span>";
    if (!d.anomalies.length) {
      box.innerHTML = "<div class=\"note\">無異常 —— 檢測方法 " + methodTag + "。所有簽發方均低於每小時 " + esc(d.threshold) + " 份的閾值。</div>";
    } else {
      box.innerHTML = "<div class=\"note\">檢測方法 " + methodTag + "</div>" + d.anomalies.map((a) =>
        "<div class=\"err\" style=\"display:block;margin-top:6px\"><b>" + esc(a.severity) +
        "</b> — " + esc(a.signer) + " 一小時內簽發 " + esc(a.credential_count) +
        " 份（閾值 " + esc(a.threshold) + "，原因: " + esc(a.reasons.join("+")) + "，最後區塊 " + esc(a.last_height) + "）。</div>"
      ).join("");
    }
    renderHourlyChart(d.hourly_issues || []);
  } catch (e) {
    $("anomalyBox").innerHTML = "<div class=\"note\">" + esc(e.message) + "</div>";
  }
}

async function loadNotifications() {
  try {
    const d = await api("/api/notifications");
    const rows = (d.notifications || []).slice().reverse().map((n) =>
      "<tr><td>" + esc(new Date(n.time * 1000).toLocaleTimeString()) + "</td>" +
      "<td>" + esc(n.to || "—") + "</td>" +
      "<td>" + esc(n.status) + "</td>" +
      "<td class=\"mono\">" + esc(n.detail || "") + "</td></tr>"
    ).join("");
    $("notifTable").innerHTML = "<tr><th>時間</th><th>收件人</th><th>狀態</th><th>説明</th></tr>" +
      (rows || "<tr><td colspan=4>暫無通知 —— 帶郵箱簽發一份試試。</td></tr>");
  } catch (e) {
    $("notifTable").innerHTML = "<tr><td colspan=4>" + esc(e.message) + "</td></tr>";
  }
}
