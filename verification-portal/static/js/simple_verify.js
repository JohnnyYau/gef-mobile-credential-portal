/* simple_verify.js — the one-screen verify page (U25, revised for the showcase).
 *
 * No framework, no tabs: take one hash or one file, ask the API for a verdict,
 * then show a single sentence a human can act on. Under it sits the part the
 * audience actually came for: what the server did, in order, with the block
 * numbers and the real response time.
 */
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var HASH_RE = /^[A-Za-z0-9_-]{16,200}$/;
  var chainBlocks = null;
  var samplesReady = false;

  var CHECKS = [
    ["chain_integrity", "链条没被改过", "整条链每个块都和当初一致"],
    ["signer_trusted", "签发方可信", "签名者是机构公布的指纹"],
    ["on_chain_record", "链上有这张证书", "不是随手编的编号"],
    ["hash_match", "文件跟编号对得上", "内容没被改过"],
    ["signature_valid", "数字签名有效", "用机构的公钥验过了"],
    ["not_revoked", "没有被注销", "机构没有撤销它"]
  ];

  var VERDICT = {
    "VALID ON CHAIN": {
      tone: "valid", mark: "✅ 真的",
      headline: "这张凭证有效",
      detail: "签名、哈希、链条都对得上，机构也没有注销它。"
    },
    "REVOKED": {
      tone: "warn", mark: "↩ 已注销",
      headline: "这张凭证已经被注销",
      detail: "签名是真的，但机构宣布它作废了。"
    },
    "NOT FOUND": {
      tone: "bad", mark: "✗ 查不到",
      headline: "链上找不到这张凭证",
      detail: "可能是假证书，也可能编号抄错了。"
    }
  };

  /* Chain reasons are typed by staff in free text; the two demo fixtures were
   * written before this page existed and read like debug lines. Translate the
   * known ones and leave everything else alone. */
  var REASONS = [
    [/issued by mistake/i, "当初签发有误（课程演示样例）"],
    [/revoked on stage/i, "在展示现场当场注销（演示）"],
    [/demo sample/i, "课程演示样例"]
  ];

  var el = function (tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) { node.className = cls; }
    if (text !== undefined && text !== null) { node.textContent = text; }
    return node;
  };

  function prettyReason(raw) {
    if (!raw) { return ""; }
    for (var i = 0; i < REASONS.length; i += 1) {
      if (REASONS[i][0].test(raw)) { return REASONS[i][1]; }
    }
    return raw;
  }

  function when(seconds) {
    if (!seconds) { return ""; }
    var d = new Date(seconds * 1000);
    var pad = function (n) { return (n < 10 ? "0" : "") + n; };
    return (d.getMonth() + 1) + "月" + pad(d.getDate()) + "日 " +
      pad(d.getHours()) + ":" + pad(d.getMinutes());
  }

  function setError(message) {
    var box = $("error");
    if (!message) {
      box.hidden = true;
      box.textContent = "";
      return;
    }
    box.textContent = message;
    box.hidden = false;
  }

  function setBusy(busy) {
    var btn = $("verifyBtn");
    btn.disabled = busy;
    btn.textContent = busy ? "正在核对…" : "验证";
  }

  function flag(value) {
    if (value === true) { return { cls: "ok", text: "✓" }; }
    if (value === false) { return { cls: "no", text: "✗" }; }
    return { cls: "na", text: "—" }; 
  }

  /* ---- the "what just happened" strip --------------------------------- */

  function traceRows(data) {
    var st = data.status || {};
    var issueHeights = st.issue_heights || [];
    var revokeHeights = st.revoke_heights || [];
    var rows = [];

    if (issueHeights.length) {
      rows.push(["取回链上记录", "第 " + issueHeights[0] + " 块" +
        (st.issued_at ? "，签发于 " + when(st.issued_at) : "")]);
    } else {
      rows.push(["取回链上记录", "这条编号没有对应的块"]);
    }

    rows.push([
      "验证数字签名",
      data.signature_valid === true ? "用机构的公钥验过，签名有效"
        : data.signature_valid === false ? "验签没通过" : "没有可验的签名"
    ]);

    rows.push([
      "比对证书内容",
      data.hash_match === true ? "文件和链上哈希一致"
        : data.hash_match === false ? "文件和链上哈希不一致"
        : "只给了编号，本次没有文件可比"
    ]);

    if (st.revoked) {
      rows.push(["查询撤销名单", "有记录：第 " + (revokeHeights[0] || "?") + " 块写过一笔注销"]);
    } else {
      rows.push(["查询撤销名单", "没有记录，机构没有注销它"]);
    }

    return rows;
  }

  function buildTrace(data, ms) {
    var rows = traceRows(data);
    var box = el("div", "trace");
    box.appendChild(el("div", "trace-title", "这次查验做了什么"));

    var list = el("ol", "trace-list");
    rows.forEach(function (row) {
      var li = el("li");
      li.appendChild(el("span", "trace-what", row[0]));
      li.appendChild(el("span", "trace-val", row[1]));
      list.appendChild(li);
    });
    box.appendChild(list);

    var tail = "本次查验 " + ms + " ms";
    if (chainBlocks) { tail = "整条链 " + chainBlocks + " 块完整性检查通过 · " + tail; }
    box.appendChild(el("p", "trace-foot", tail));
    return box;
  }

  /* ---- the verdict card ------------------------------------------------ */

  function buildResult(data, ms) {
    var hash = data.hashed_document || "";
    var known = VERDICT[data.verdict];
    var tone = known ? known.tone : "bad";
    var mark = known ? known.mark : "⚠ 无法确认";
    var headline = known ? known.headline : "这张凭证没有通过检查";
    var detail = known ? known.detail : "";

    if (data.verdict === "REVOKED") {
      var reason = prettyReason(data.reason);
      if (reason) { detail = "原因：" + reason + "。"; }
      if (data.effective_at) { detail += " 生效时间：" + data.effective_at + "。"; }
    }
    if (!known && data.verdict) { detail = "系统判定：" + data.verdict + "。"; }

    var box = el("div", "verdict " + tone);
    box.appendChild(el("div", "mark", mark));
    box.appendChild(el("div", "headline", headline));
    if (detail) { box.appendChild(el("p", "detail", detail)); }

    /* the six checks, folded away */
    var why = el("details", "why");
    why.appendChild(el("summary", null, "为什么？看六项检查"));
    var list = el("ul", "checks");
    CHECKS.forEach(function (row) {
      var state = flag(data[row[0]]);
      var li = el("li");
      li.appendChild(el("span", "flag " + state.cls, state.text));
      var body = el("span");
      body.appendChild(el("span", null, row[1]));
      body.appendChild(el("span", "desc", row[2]));
      if (data[row[0]] === null) { body.appendChild(el("span", "desc", "未提供文件，只有编号时无法比对")); }
      li.appendChild(body);
      list.appendChild(li);
    });
    why.appendChild(list);
    box.appendChild(why);

    var actions = el("div", "actions");
    if (hash && data.verdict === "VALID ON CHAIN") {
      var report = el("a", "ghost", "下载验证报告");
      report.href = "/api/pdf/" + hash;
      report.target = "_blank";
      report.rel = "noopener";
      actions.appendChild(report);
    }
    if (hash) {
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

      var again = el("button", "linkish", "再验一张");
      again.type = "button";
      again.addEventListener("click", reset);
      actions.appendChild(again);
    }

    var out = $("result");
    out.textContent = "";
    out.appendChild(box);
    if (actions.childNodes.length) { out.appendChild(actions); }
    out.appendChild(buildTrace(data, ms));
    if (hash) { out.appendChild(el("div", "hashbox", hash)); }
    if (data.receipt_id) { out.appendChild(el("p", "hint", "回执编号 " + data.receipt_id)); }
    out.hidden = false;
    /* The form has done its job; folding it away lifts the verdict and the
     * trace into the first screen instead of leaving them below the fold. */
    $("verifyForm").hidden = true;
    $("samples").hidden = true;

    if (out.getBoundingClientRect().top > window.innerHeight - 140) {
      out.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }

  function reset() {
    $("result").hidden = true;
    $("result").textContent = "";
    $("verifyForm").hidden = false;
    if (samplesReady) { $("samples").hidden = false; }
    $("hashInput").value = "";
    $("fileInput").value = "";
    $("fileLabel").textContent = "选择证书文件（PDF / JSON）";
    $("fileBox").classList.remove("armed");
    setError("");
    $("hashInput").focus();
  }

  function fail(res, body) {
    var message = "验证失败（" + res.status + "）";
    if (body && typeof body.detail === "string") { message = body.detail; }
    else if (body && body.detail) { message = "输入有误，请检查后再试。"; }
    setError(message);
  }

  async function verifyHash(hash) {
    setBusy(true);
    setError("");
    var started = Date.now();
    try {
      var res = await fetch("/api/verify/" + encodeURIComponent(hash), { headers: { "Accept": "application/json" } });
      var body = await res.json().catch(function () { return null; });
      if (!res.ok) { fail(res, body); return; }
      buildResult(body, Date.now() - started);
    } catch (err) {
      setError("连不上验证服务：" + err.message);
    } finally {
      setBusy(false);
    }
  }

  async function verifyFile(file) {
    setBusy(true);
    setError("");
    var started = Date.now();
    try {
      var form = new FormData();
      form.append("file", file);
      var res = await fetch("/api/verify/document", { method: "POST", body: form });
      var body = await res.json().catch(function () { return null; });
      if (!res.ok) { fail(res, body); return; }
      buildResult(body, Date.now() - started);
    } catch (err) {
      setError("上传失败：" + err.message);
    } finally {
      setBusy(false);
    }
  }

  function onSubmit(event) {
    event.preventDefault();
    var file = $("fileInput").files[0];
    if (file) { verifyFile(file); return; }
    var raw = ($("hashInput").value || "").trim();
    if (!raw) { setError("先粘贴验证码，或选一个文件。"); return; }
    var hash = raw.split(/[?&]hash=/).pop().replace(/[\s"'<>]/g, "");
    if (!HASH_RE.test(hash)) { setError("这段不像验证码：应为 16–200 个字母数字、- 或 _。"); return; }
    verifyHash(hash);
  }

  function sampleChip(label, hash) {
    var chip = el("button", "chip", label);
    chip.type = "button";
    chip.addEventListener("click", function () {
      $("fileInput").value = "";
      $("fileLabel").textContent = "选择证书文件（PDF / JSON）";
      $("fileBox").classList.remove("armed");
      $("hashInput").value = hash;
      verifyHash(hash);
    });
    return chip;
  }

  async function loadSamples() {
    var results = await Promise.allSettled([
      fetch("/api/demo/credentials").then(function (r) { return r.ok ? r.json() : null; }),
      fetch("/api/statuslist").then(function (r) { return r.ok ? r.json() : null; })
    ]);
    var chips = [];
    var demo = results[0].status === "fulfilled" ? results[0].value : null;
    var list = results[1].status === "fulfilled" ? results[1].value : null;

    if (demo && demo.diploma && demo.diploma.hashed_document) {
      chips.push(sampleChip("✅ 真实有效", demo.diploma.hashed_document));
    }
    if (list && Array.isArray(list.revoked) && list.revoked.length) {
      chips.push(sampleChip("↩ 已注销", list.revoked[0].hash));
    }
    chips.push(sampleChip("⚠ 查无此证", new Array(87).join("A")));

    if (!chips.length) { return; }
    var box = $("chips");
    chips.forEach(function (chip) { box.appendChild(chip); });
    samplesReady = true;
    if ($("result").hidden) { $("samples").hidden = false; }
  }

  async function loadChainHeight() {
    try {
      var res = await fetch("/healthz", { headers: { "Accept": "application/json" } });
      if (!res.ok) { return; }
      var body = await res.json();
      if (body && body.height) { chainBlocks = body.height; }
    } catch (err) { /* the strip just omits the chain line */ }
  }

  function init() {
    $("verifyForm").addEventListener("submit", onSubmit);
    $("hashInput").addEventListener("input", function () { setError(""); });
    $("fileInput").addEventListener("change", function (event) {
      var file = event.target.files[0];
      if (!file) { return; }
      $("fileLabel").textContent = file.name + " · " + Math.round(file.size / 1024) + " KB";
      $("fileBox").classList.add("armed");
      $("hashInput").value = "";
      setError("");
    });

    var params = new URLSearchParams(window.location.search);
    var deep = params.get("hash") || params.get("h");
    if (deep && HASH_RE.test(deep)) {
      $("hashInput").value = deep;
      verifyHash(deep);
    }
    loadSamples();
    loadChainHeight();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
}());
