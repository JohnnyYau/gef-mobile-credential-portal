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

  /* /api/admin/pdf and /api/custom/file are staff routes: a plain <a> opens them
   * in a new tab with no X-Admin-Token and gets 401. Fetch with the token and
   * hand the blob to the browser instead. */
  function adminHeaders() {
    var headers = { "Accept": "application/pdf, application/json" };
    var t = token() || sessionStorage.getItem(TOKEN_KEY) || "";
    if (t) { headers["X-Admin-Token"] = t; }
    return headers;
  }

  async function saveFile(url, filename, button) {
    var label = button.textContent;
    button.disabled = true;
    button.textContent = "下載中…";
    try {
      var res = await fetch(url, { headers: adminHeaders() });
      if (!res.ok) {
        setError(res.status === 401 || res.status === 403
          ? "下載要機構口令：在上面那格填一次，這台瀏覽器就會記住。"
          : "下載失敗（" + res.status + "）。");
        return;
      }
      var blob = await res.blob();
      var href = URL.createObjectURL(blob);
      var a = document.createElement("a");
      a.href = href;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(function () { URL.revokeObjectURL(href); }, 4000);
    } catch (err) {
      setError("下載失敗：" + err.message);
    } finally {
      button.disabled = false;
      button.textContent = label;
    }
  }

  function showResult(data, studentId) {
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

    /* /api/admin/pdf is an admin route: a plain <a> opens it in a new tab with
     * no X-Admin-Token header and gets 401. Fetch it with the token instead. */
    var pdf = el("button", "ghost", "下載憑證 PDF");
    pdf.type = "button";
    pdf.addEventListener("click", function () {
      saveFile("/api/admin/pdf/" + encodeURIComponent(hash),
               "credential-" + hash.slice(0, 10) + ".pdf", pdf);
    });
    actions.appendChild(pdf);

    if (data.file_id) {
      var json = el("button", "ghost", "下載 JSON");
      json.type = "button";
      json.addEventListener("click", function () {
        saveFile("/api/custom/file/" + encodeURIComponent(data.file_id) + "/json",
                 "credential-" + hash.slice(0, 10) + ".json", json);
      });
      actions.appendChild(json);
    }

    var sid = studentId || (data.document && data.document.PersonalParticulars
      && data.document.PersonalParticulars.StudentID) || "";
    if (sid) {
      var link = el("button", "ghost", "複製學生連結");
      link.type = "button";
      link.addEventListener("click", async function () {
        link.disabled = true;
        try {
          var res = await fetch("/api/holder-link?student_id=" + encodeURIComponent(sid) +
                                "&hashed_document=" + encodeURIComponent(hash),
                                { headers: adminHeaders() });
          var body = await res.json().catch(function () { return null; });
          if (!res.ok || !body || !body.path) {
            setError(res.status === 401 || res.status === 403
              ? "拿連結要機構口令：在上面那格填一次。"
              : "拿不到學生連結（" + res.status + "）。");
            return;
          }
          var url = location.origin + body.path;
          if (!navigator.clipboard) { setError(url); return; }
          await navigator.clipboard.writeText(url);
          link.textContent = "已複製連結";
          setTimeout(function () { link.textContent = "複製學生連結"; }, 1600);
        } catch (err) {
          setError("拿不到學生連結：" + err.message);
        } finally {
          link.disabled = false;
        }
      });
      actions.appendChild(link);
    }

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
    out.appendChild(el("p", "hint",
      "把學生連結給對方：他自己能下載 PDF，也能隨時看這張憑證還有效沒有效。"));
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
      showResult(data, body.student_id);
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
