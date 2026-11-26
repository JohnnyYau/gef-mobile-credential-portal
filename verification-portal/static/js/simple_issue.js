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
    btn.textContent = busy ? "签发中…（首次生成密钥可能要几秒）" : "签发并上链";
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
    box.appendChild(el("div", "mark", "✅ 已上链"));
    box.appendChild(el("div", "headline", height ? "这张证书现在是第 " + height + " 块" : "这张证书已签发"));
    box.appendChild(el("p", "detail", "任何人拿这个验证码都能查到它；改一个字符就查不到。"));

    var actions = el("div", "actions");
    var open = el("a", "ghost", "打开验证页看看");
    open.href = "/verify?hash=" + encodeURIComponent(hash);
    actions.appendChild(open);

    var pdf = el("a", "ghost", "下载凭证 PDF");
    pdf.href = "/api/admin/pdf/" + encodeURIComponent(hash);
    pdf.target = "_blank";
    pdf.rel = "noopener";
    actions.appendChild(pdf);

    var copy = el("button", "ghost", "复制验证码");
    copy.type = "button";
    copy.addEventListener("click", function () {
      if (navigator.clipboard) {
        navigator.clipboard.writeText(hash).then(function () {
          copy.textContent = "已复制";
          setTimeout(function () { copy.textContent = "复制验证码"; }, 1600);
        });
      }
    });
    actions.appendChild(copy);

    out.appendChild(box);
    out.appendChild(actions);
    out.appendChild(el("div", "hashbox", hash));
    out.appendChild(el("p", "hint", "把 PDF 或这串验证码给对方，就可以验了。"));
    $("tokenHint").textContent = "口令已记住，这台浏览器下次不用再填。";
    out.hidden = false;
    out.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  async function submit(event) {
    event.preventDefault();
    setError("");
    var body = payload();
    if (!body.name || !body.student_id || !body.degree) {
      setError("姓名、学号、学位三格都要填。");
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
        $("tokenHint").textContent = "口令不对，或这台浏览器还没有机构会话。";
        setError("需要机构口令才能签发。");
        return;
      }
      if (!res.ok) {
        var message = "签发失败（" + res.status + "）";
        if (data && typeof data.detail === "string") { message = data.detail; }
        setError(message);
        return;
      }
      if (t) { sessionStorage.setItem(TOKEN_KEY, t); }
      showResult(data);
    } catch (err) {
      setError("连不上签发服务：" + err.message);
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
