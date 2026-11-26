/* showtime.js — the stage screen (U26).
 *
 * Four steps, all real: POST /api/custom/build, GET /api/verify, POST
 * /api/revoke, GET /api/verify again. Nothing here is a canned animation —
 * if the chain is down the screen says so.
 */
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var TOKEN_KEY = "gef26_issue_token";
  var student = "";

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) { node.className = cls; }
    if (text !== undefined && text !== null) { node.textContent = text; }
    return node;
  }

  function note(message) {
    var box = $("note");
    if (!message) { box.hidden = true; box.textContent = ""; return; }
    box.textContent = message;
    box.hidden = false;
  }

  function head(text, tone, sub) {
    var line = $("headline");
    line.textContent = text;
    line.className = tone ? "wait " + tone : "wait";
    if (sub !== undefined) { $("subline").textContent = sub; }
  }

  function hashLine(text) {
    var box = $("hashline");
    if (!text) { box.hidden = true; box.textContent = ""; return; }
    box.textContent = text;
    box.hidden = false;
  }

  function qr(hash) {
    var wrap = $("qrwrap");
    if (!hash) { wrap.hidden = true; wrap.textContent = ""; return; }
    wrap.textContent = "";
    var img = el("img");
    img.src = "/api/qr/" + encodeURIComponent(hash);
    img.alt = "掃描驗證這張證書";
    img.width = 260;
    img.height = 260;
    wrap.appendChild(img);
    wrap.appendChild(el("p", "qrcap", "掃一下，用手機看它現在的狀態"));
    wrap.hidden = false;
  }

  function steps(upto) {
    var all = document.querySelectorAll(".step");
    Array.prototype.forEach.call(all, function (node) {
      var n = Number(node.getAttribute("data-step"));
      node.classList.toggle("on", n === upto);
      node.classList.toggle("done", n < upto || (upto === 5 && n <= 4));
    });
  }

  /* Each step keeps a receipt of what actually happened, so the row of four
   * cards stops being decoration and starts being the proof. */
  function markStep(n, text) {
    var node = document.querySelector('.step[data-step="' + n + '"] .meta');
    if (node) { node.textContent = text; }
  }

  function clearSteps() {
    Array.prototype.forEach.call(document.querySelectorAll(".step .meta"), function (node) {
      node.textContent = "";
    });
  }

  function secs(ms) {
    if (ms < 1000) { return Math.round(ms) + " ms"; }
    return (ms / 1000).toFixed(1) + "s";
  }

  function meter(height, signers) {
    if (height !== undefined && height !== null) { $("height").textContent = height; }
    if (signers !== undefined && signers !== null) { $("signers").textContent = signers; }
  }

  function wait(ms) { return new Promise(function (resolve) { setTimeout(resolve, ms); }); }

  function token() {
    var saved = sessionStorage.getItem(TOKEN_KEY);
    var typed = ($("tokenInput").value || "").trim();
    return typed || saved || "";
  }

  async function call(path, options) {
    var headers = { "Accept": "application/json" };
    var t = token();
    if (t) { headers["X-Admin-Token"] = t; }
    if (options && options.body) { headers["Content-Type"] = "application/json"; }
    var res = await fetch(path, {
      method: (options && options.method) || "GET",
      headers: headers,
      body: options && options.body ? JSON.stringify(options.body) : undefined
    });
    var body = await res.json().catch(function () { return null; });
    return { ok: res.ok, status: res.status, body: body };
  }

  async function refreshMeter() {
    try {
      var hz = await call("/healthz");
      if (hz.ok) {
        meter(hz.body.height, (hz.body.signers || []).length || hz.body.num_signers);
      }
    } catch (err) { /* the meter is decoration; the steps still speak */ }
  }

  async function run() {
    note("");
    clearSteps();
    $("startBtn").disabled = true;
    $("resetBtn").hidden = true;
    $("hint").hidden = true;
    hashLine("");
    qr("");

    var stamp = String(Date.now()).slice(-5);
    student = "26" + stamp;

    /* ---- 01 issue ---- */
    steps(1);
    head("正在簽發…", null, "真的會寫一個新區塊，可能要等一兩秒。");
    var t0 = performance.now();
    var issued = await call("/api/custom/build", {
      method: "POST",
      body: {
        name: "ZHANG XIAOMING",
        student_id: student,
        degree: "Bachelor of Engineering",
        honour: "1ST HON",
        issue: true
      }
    }).catch(function (err) { return { ok: false, status: 0, body: { detail: err.message } }; });
    var dIssue = performance.now() - t0;

    if (!issued.ok) {
      if (issued.status === 401 || issued.status === 403) {
        $("tokenInput").hidden = false;
        note("需要機構口令：填在下面這格，再按開始。");
        head("沒有權限簽發", "dead", "這台機器上沒有機構會話。");
      } else {
        note("簽發失敗：" + ((issued.body && issued.body.detail) || issued.status));
        head("簽發失敗", "dead", "看下面的提示。");
      }
      $("startBtn").disabled = false;
      return;
    }

    var hash = issued.body.hashed_document;
    var height = issued.body.height;
    markStep(1, "第 " + height + " 塊 · " + secs(dIssue));
    steps(2);
    head("已上鍊 · 第 " + height + " 塊", "go",
         "ZHANG XIAOMING · Bachelor of Engineering · 學號 " + student + "，簽發機構 UNIVERSITY OF UTOPIA。");
    hashLine(hash);
    qr(hash);
    $("hint").hidden = false;
    meter(height);
    await wait(2400);

    /* ---- 02 verify ---- */
    head("正在驗證同一張證書…", null, "任何人拿這個驗證碼都能查，不用登錄。");
    var t1 = performance.now();
    var first = await call("/api/verify/" + encodeURIComponent(hash));
    var dVerify = performance.now() - t1;
    if (!first.ok) {
      note("驗證失敗：" + first.status);
      head("驗證失敗", "dead", "");
      $("startBtn").disabled = false;
      return;
    }
    steps(3);
    if (first.body.verdict === "VALID ON CHAIN") {
      head("✅ 真的", "go", "六項檢查全部通過，鏈上第 " + (first.body.height || height) + " 塊。");
      markStep(2, "VALID · " + secs(dVerify));
    } else {
      head("判定：" + first.body.verdict, "stop", "不是 VALID，説明這次簽發沒落好。");
      markStep(2, first.body.verdict);
    }
    await wait(2600);

    /* ---- 03 revoke ---- */
    steps(4);
    head("正在註銷這張證書…", null, "機構改主意了——這個動作會寫一條 REVOKE 塊。");
    var t2 = performance.now();
    var revoked = await call("/api/revoke", {
      method: "POST",
      body: { hashed_document: hash, reason: "在展示現場當場註銷（演示）" }
    }).catch(function (err) { return { ok: false, status: 0 }; });
    var dRevoke = performance.now() - t2;

    if (!revoked.ok) {
      note("註銷失敗：" + revoked.status + "（" + ((revoked.body && revoked.body.detail) || "") + "）");
      $("startBtn").disabled = false;
      return;
    }
    markStep(3, "第 " + (revoked.body.height || "?") + " 塊 · " + secs(dRevoke));
    head("已註銷 · 第 " + (revoked.body.height || "?") + " 塊", "stop",
         "注意：簽名沒有失效，失效的是機構的承諾。");
    meter(revoked.body.height);
    await wait(2200);

    /* ---- 04 verify again ---- */
    head("再驗一次同一張…", null, "");
    var t3 = performance.now();
    var second = await call("/api/verify/" + encodeURIComponent(hash));
    var dSecond = performance.now() - t3;
    steps(5);
    if (second.ok && second.body.verdict === "REVOKED") {
      head("↩ 已註銷", "stop",
           "簽名仍然有效、哈希仍然對得上 —— 但機構説它作廢了。這就是區別。");
      markStep(4, "REVOKED · " + secs(dSecond));
    } else if (second.ok) {
      head("判定：" + second.body.verdict, "stop", "預期是 REVOKED。");
      markStep(4, second.body.verdict);
    } else {
      head("驗證失敗", "dead", String(second.status));
    }
    $("startBtn").disabled = false;
    $("startBtn").hidden = true;
    $("resetBtn").hidden = false;
    refreshMeter();
  }

  function reset() {
    steps(0);
    clearSteps();
    head("按左下角「開始」，四步走完大約 12 秒。", null,
         "每一步都是真實的 API 調用：真的簽發、真的上鍊、真的註銷。");
    hashLine("");
    qr("");
    note("");
    $("hint").hidden = true;
    $("resetBtn").hidden = true;
    $("startBtn").hidden = false;
    $("startBtn").disabled = false;
  }

  function init() {
    $("startBtn").addEventListener("click", function () { run(); });
    $("resetBtn").addEventListener("click", reset);
    var params = new URLSearchParams(window.location.search);
    var t = params.get("token");
    if (t) { sessionStorage.setItem(TOKEN_KEY, t); }
    refreshMeter();
    if (params.get("auto") === "1") { run(); }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
}());
