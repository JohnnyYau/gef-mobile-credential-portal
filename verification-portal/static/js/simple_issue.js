/* simple_issue.js — the three-field issuing page (U25).
 *
 * Same guarded endpoint the staff console uses (POST /api/custom/build); this
 * page only cuts the form down to what an issuing clerk actually types.
 */
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var TOKEN_KEY = "gef26_issue_token";

  var el = function (tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) { node.className = cls; }
    if (text !== undefined && text !== null) { node.textContent = text; }
    return node;
  };

  function setError(message) {
    var box = $("error");
    if (!message) { box.hidden = true; box.textContent = ""; return; }
    box.textContent = message;
    box.hidden = false;
  }

  function setBusy(busy) {
    var btn = $("issueBtn");
    btn.disabled = busy;
    btn.textContent = busy ? "簽發中…（首次生成密鑰可能要幾秒）" : "簽發並上鏈";
  }

  function token() { return ($("tokenInput").value || "").trim(); }

  async function checkSession() {
    try {
      var res = await fetch("/api/staff/whoami", { headers: { "Accept": "application/json" } });
      if (res.ok) {
        $("tokenBlock").hidden = true;
        return true;
      }
    } catch (err) { /* fall through to the token box */ }
    $("tokenBlock").hidden = false;
    var saved = sessionStorage.getItem(TOKEN_KEY);
    if (saved) { $("tokenInput").value = saved; }
    return false;
  }

  function payload() {
    var body = {
      name: ($("nameInput").value || "").trim(),
      student_id: ($("sidInput").value || "").trim(),
      degree: ($("degreeInput").value || "").trim(),
      issue: true
    };
    var honour = ($("honourInput").value || "").trim();
    var issuer = ($("issuerInput").value || "").trim();
    var date = ($("dateInput").value || "").trim();
    if (honour) { body.honour = honour; }
    if (issuer) { body.issuer = issuer; }
    if (date) { body.date_of_issue = date; }
    return body;
  }

  function showResult(data) {
    var hash = data.hashed_document || "";
    var height = data.height;
    var out = $("result");
    out.textContent = "";

    var box = el("div", "verdict valid");
    box.appendChild(el("div", "mark", "✅ 已上鍊"));
    box.appendChild(el("div", "headline", height ? "這張證書現在是第 " + height + " 塊" : "這張證書已簽發"));
    box.appendChild(el("p", "detail", "任何人拿這個驗證碼都能查到它；改一個字符就查不到。"));

    var actions = el("div", "actions");
    var open = el("a", "ghost", "打開驗證頁看看");
    open.href = "/verify?hash=" + encodeURIComponent(hash);
    actions.appendChild(open);

    var pdf = el("a", "ghost", "下載憑證 PDF");
    pdf.href = "/api/admin/pdf/" + encodeURIComponent(hash);
    pdf.target = "_blank";
    pdf.rel = "noopener";
    actions.appendChild(pdf);

    var copy = el("button", "ghost", "複製驗證碼");
    copy.type = "button";
    copy.addEventListener("click", function () {
      if (navigator.clipboard) {
        navigator.clipboard.writeText(hash).then(function () {
          copy.textContent = "已複製";
          setTimeout(function () { copy.textContent = "複製驗證碼"; }, 1600);
        });
      }
    });
    actions.appendChild(copy);

    out.appendChild(box);
    out.appendChild(actions);
    out.appendChild(el("div", "hashbox", hash));
    out.appendChild(el("p", "hint", "把 PDF 或這串驗證碼給對方，就可以驗了。"));
    $("tokenHint").textContent = "口令已記住，這台瀏覽器下次不用再填。";
    out.hidden = false;
    out.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  async function submit(event) {
    event.preventDefault();
    setError("");
    var body = payload();
    if (!body.name || !body.student_id || !body.degree) {
      setError("姓名、學號、學位三格都要填。");
      return;
    }

    setBusy(true);
    var headers = { "Content-Type": "application/json", "Accept": "application/json" };
    var t = token();
    if (t) { headers["X-Admin-Token"] = t; }

    try {
      var res = await fetch("/api/custom/build", {
        method: "POST", headers: headers, body: JSON.stringify(body)
      });
      var data = await res.json().catch(function () { return null; });
      if (res.status === 401 || res.status === 403) {
        $("tokenBlock").hidden = false;
        $("tokenHint").textContent = "口令不對，或這台瀏覽器還沒有機構會話。";
        setError("需要機構口令才能簽發。");
        return;
      }
      if (!res.ok) {
        var message = "簽發失敗（" + res.status + "）";
        if (data && typeof data.detail === "string") { message = data.detail; }
        setError(message);
        return;
      }
      if (t) { sessionStorage.setItem(TOKEN_KEY, t); }
      showResult(data);
    } catch (err) {
      setError("連不上籤發服務：" + err.message);
    } finally {
      setBusy(false);
    }
  }

  function init() {
    $("issueForm").addEventListener("submit", submit);
    checkSession();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
}());
