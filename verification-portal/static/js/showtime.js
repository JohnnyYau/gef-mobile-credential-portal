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
    img.alt = "扫描验证这张证书";
    img.width = 200;
    img.height = 200;
    wrap.appendChild(img);
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
    $("startBtn").disabled = true;
    $("resetBtn").hidden = true;
    $("hint").hidden = true;
    hashLine("");
    qr("");

    var stamp = String(Date.now()).slice(-5);
    student = "26" + stamp;

    /* ---- 01 issue ---- */
    steps(1);
    head("正在签发…", null, "真的会写一个新区块，可能要等一两秒。");
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

    if (!issued.ok) {
      if (issued.status === 401 || issued.status === 403) {
        $("tokenInput").hidden = false;
        note("需要机构口令：填在右下角，再按开始。");
        head("没有权限签发", "dead", "这台机器上没有机构会话。");
      } else {
        note("签发失败：" + ((issued.body && issued.body.detail) || issued.status));
        head("签发失败", "dead", "看右下角的提示。");
      }
      $("startBtn").disabled = false;
      return;
    }

    var hash = issued.body.hashed_document;
    var height = issued.body.height;
    steps(2);
    head("已上链 · 第 " + height + " 块", "go",
         "证书属于 " + student + "，签发机构 UNIVERSITY OF UTOPIA。");
    hashLine(hash);
    qr(hash);
    $("hint").hidden = false;
    meter(height);
    await wait(2400);

    /* ---- 02 verify ---- */
    head("正在验证同一张证书…", null, "任何人拿这个验证码都能查，不用登录。");
    var first = await call("/api/verify/" + encodeURIComponent(hash));
    if (!first.ok) {
      note("验证失败：" + first.status);
      head("验证失败", "dead", "");
      $("startBtn").disabled = false;
      return;
    }
    steps(3);
    if (first.body.verdict === "VALID ON CHAIN") {
      head("✅ 真的", "go", "六项检查全部通过，链上第 " + (first.body.height || height) + " 块。");
    } else {
      head("判定：" + first.body.verdict, "stop", "不是 VALID，说明这次签发没落好。");
    }
    await wait(2600);

    /* ---- 03 revoke ---- */
    steps(4);
    head("正在注销这张证书…", null, "机构改主意了——这个动作会写一条 REVOKE 块。");
    var revoked = await call("/api/revoke", {
      method: "POST",
      body: { hashed_document: hash, reason: "SHOWCASE demo: revoked on stage" }
    }).catch(function (err) { return { ok: false, status: 0 }; });

    if (!revoked.ok) {
      note("注销失败：" + revoked.status + "（" + ((revoked.body && revoked.body.detail) || "") + "）");
      $("startBtn").disabled = false;
      return;
    }
    head("已注销 · 第 " + (revoked.body.height || "?") + " 块", "stop",
         "注意：签名没有失效，失效的是机构的承诺。");
    meter(revoked.body.height);
    await wait(2200);

    /* ---- 04 verify again ---- */
    head("再验一次同一张…", null, "");
    var second = await call("/api/verify/" + encodeURIComponent(hash));
    steps(5);
    if (second.ok && second.body.verdict === "REVOKED") {
      head("↩ 已注销", "stop",
           "签名仍然有效、哈希仍然对得上 —— 但机构说它作废了。这就是区别。");
    } else if (second.ok) {
      head("判定：" + second.body.verdict, "stop", "预期是 REVOKED。");
    } else {
      head("验证失败", "dead", String(second.status));
    }
    $("startBtn").disabled = false;
    $("resetBtn").hidden = false;
    refreshMeter();
  }

  function reset() {
    steps(0);
    head("按「开始」，四步走完大约 12 秒。", null,
         "每一步都是真实的 API 调用：真的签发、真的上链、真的注销。");
    hashLine("");
    qr("");
    note("");
    $("hint").hidden = true;
    $("resetBtn").hidden = true;
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
