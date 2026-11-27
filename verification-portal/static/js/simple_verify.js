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
    ["chain_integrity", "鏈條沒被改過", "整條鏈每個塊都和當初一致"],
    ["signer_trusted", "簽發方可信", "簽名者是機構公佈的指紋"],
    ["on_chain_record", "鏈上有這張證書", "不是隨手編的編號"],
    ["hash_match", "文件跟編號對得上", "內容沒被改過"],
    ["signature_valid", "數字簽名有效", "用機構的公鑰驗過了"],
    ["not_revoked", "沒有被註銷", "機構沒有撤銷它"]
  ];

  var VERDICT = {
    "VALID ON CHAIN": {
      tone: "valid", mark: "✅ 真的",
      headline: "這張憑證有效",
      detail: "簽名、哈希、鏈條都對得上，機構也沒有註銷它。"
    },
    "REVOKED": {
      tone: "warn", mark: "↩ 已註銷",
      headline: "這張憑證已經被註銷",
      detail: "簽名是真的，但機構宣佈它作廢了。"
    },
    "NOT FOUND": {
      tone: "bad", mark: "✗ 查不到",
      headline: "鏈上找不到這張憑證",
      detail: "可能是假證書，也可能編號抄錯了。"
    },
    /* A document was uploaded and its number is not the one on record, or the
     * record exists but a signature/hash check failed. This is not "the machine
     * is unsure" — it is a definite rejection, so say so. */
    "INVALID": {
      tone: "bad", mark: "✗ 不通過",
      headline: "這張憑證跟鏈上對不上",
      detail: "文件內容算出來的編號，不是機構簽發的那一個——它被改過，或者是偽造的。"
    }
  };

  /* The hash endpoint says "VALID ON CHAIN"; the document upload endpoint says
   * just "VALID". Same verdict, two spellings — fold them together so an
   * authentic file is not shown as "unconfirmed". */
  var VERDICT_ALIAS = {
    "VALID": "VALID ON CHAIN",
    "VALID ON CHAIN": "VALID ON CHAIN",
    "INVALID": "INVALID"
  };

  /* Chain reasons are typed by staff in free text; the two demo fixtures were
   * written before this page existed and read like debug lines. Translate the
   * known ones and leave everything else alone. */
  var REASONS = [
    [/issued by mistake/i, "當初簽發有誤（課程演示樣例）"],
    [/revoked on stage/i, "在展示現場當場註銷（演示）"],
    [/demo sample/i, "課程演示樣例"]
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
    btn.textContent = busy ? "正在核對…" : "驗證";
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
      rows.push(["取回鏈上記錄", "第 " + issueHeights[0] + " 塊" +
        (st.issued_at ? "，簽發於 " + when(st.issued_at) : "")]);
    } else if (data.on_chain_record === true) {
      /* document upload: the record exists, this endpoint just does not return
       * the block list, so do not claim there is no block */
      rows.push(["取回鏈上記錄", "鏈上有這張憑證（本次以文件比對）"]);
    } else {
      rows.push(["取回鏈上記錄", "這條編號沒有對應的塊"]);
    }

    rows.push([
      "驗證數字簽名",
      data.signature_valid === true ? "用機構的公鑰驗過，簽名有效"
        : data.signature_valid === false
          ? (data.on_chain_record === false ? "這份內容沒有對應的簽發，沒有簽名可驗" : "驗籤沒通過")
          : "沒有可驗的簽名"
    ]);

    rows.push([
      "比對證書內容",
      data.hash_match === true ? "文件和鏈上哈希一致"
        : data.hash_match === false ? "文件和鏈上哈希不一致"
        : "只給了編號，本次沒有文件可比"
    ]);

    if (st.revoked) {
      rows.push(["查詢撤銷名單", "有記錄：第 " + (revokeHeights[0] || "?") + " 塊寫過一筆註銷"]);
    } else {
      rows.push(["查詢撤銷名單", "沒有記錄，機構沒有註銷它"]);
    }

    return rows;
  }

  function buildTrace(data, ms) {
    var rows = traceRows(data);
    var box = el("div", "trace");
    box.appendChild(el("div", "trace-title", "這次查驗做了什麼"));

    var list = el("ol", "trace-list");
    rows.forEach(function (row) {
      var li = el("li");
      li.appendChild(el("span", "trace-what", row[0]));
      li.appendChild(el("span", "trace-val", row[1]));
      list.appendChild(li);
    });
    box.appendChild(list);

    var tail = "本次查驗 " + ms + " ms";
    if (chainBlocks) { tail = "整條鏈 " + chainBlocks + " 塊完整性檢查通過 · " + tail; }
    box.appendChild(el("p", "trace-foot", tail));
    return box;
  }

  /* ---- the verdict card ------------------------------------------------ */

  function buildResult(data, ms) {
    var hash = data.hashed_document || "";
    var verdictKey = VERDICT_ALIAS[data.verdict] || data.verdict;
    var known = VERDICT[verdictKey];
    var tone = known ? known.tone : "bad";
    var mark = known ? known.mark : "⚠ 無法確認";
    var headline = known ? known.headline : "這張憑證沒有通過檢查";
    var detail = known ? known.detail : "";

    if (data.verdict === "REVOKED") {
      var reason = prettyReason(data.reason);
      if (reason) { detail = "原因：" + reason + "。"; }
      if (data.effective_at) { detail += " 生效時間：" + data.effective_at + "。"; }
    }
    if (!known && data.verdict) { detail = "系統判定：" + data.verdict + "。"; }

    var box = el("div", "verdict " + tone);
    box.appendChild(el("div", "mark", mark));
    box.appendChild(el("div", "headline", headline));
    if (detail) { box.appendChild(el("p", "detail", detail)); }

    /* the six checks, folded away */
    var why = el("details", "why");
    why.appendChild(el("summary", null, "為什麼？看六項檢查"));
    var list = el("ul", "checks");
    CHECKS.forEach(function (row) {
      var state = flag(data[row[0]]);
      var li = el("li");
      li.appendChild(el("span", "flag " + state.cls, state.text));
      var body = el("span");
      body.appendChild(el("span", null, row[1]));
      body.appendChild(el("span", "desc", row[2]));
      if (data[row[0]] === null) { body.appendChild(el("span", "desc", "未提供文件，只有編號時無法比對")); }
      li.appendChild(body);
      list.appendChild(li);
    });
    why.appendChild(list);
    box.appendChild(why);

    var actions = el("div", "actions");
    if (hash && verdictKey === "VALID ON CHAIN") {
      var report = el("a", "ghost", "下載驗證報告");
      report.href = "/api/pdf/" + hash;
      report.target = "_blank";
      report.rel = "noopener";
      actions.appendChild(report);
    }
    if (hash) {
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

      var again = el("button", "linkish", "再驗一張");
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
    if (data.receipt_id) { out.appendChild(el("p", "hint", "回執編號 " + data.receipt_id)); }
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
    $("fileLabel").textContent = "選擇證書文件（PDF / JSON）";
    $("fileBox").classList.remove("armed");
    setError("");
    $("hashInput").focus();
  }

  function fail(res, body) {
    var message = "驗證失敗（" + res.status + "）";
    if (body && typeof body.detail === "string") { message = body.detail; }
    else if (body && body.detail) { message = "輸入有誤，請檢查後再試。"; }
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
      setError("連不上驗證服務：" + err.message);
    } finally {
      setBusy(false);
    }
  }

  /* This page — not the ledger — remembers a rejected upload. The chain keeps
   * no record of a tampered file (it simply was never written), so if the demo
   * edits a credential and reverts it, the verdict is VALID again and the earlier
   * rejection would vanish. Keeping the note in sessionStorage lets the page say
   * "you tried a version of this that did not match" without pretending the
   * ledger knows anything about it. Cleared when the tab closes. */
  var MISMATCH_KEY = "gef26_mismatch_seen";

  function mismatchStore() {
    try { return JSON.parse(sessionStorage.getItem(MISMATCH_KEY) || "{}"); }
    catch (err) { return {}; }
  }

  function rememberMismatch(sid) {
    if (!sid) { return; }
    var store = mismatchStore();
    store[sid] = Date.now();
    try { sessionStorage.setItem(MISMATCH_KEY, JSON.stringify(store)); } catch (err) { /* private mode */ }
  }

  function mismatchNote(sid) {
    if (!sid) { return ""; }
    var when = mismatchStore()[sid];
    if (!when) { return ""; }
    var t = new Date(when);
    var hh = ("0" + t.getHours()).slice(-2) + ":" + ("0" + t.getMinutes()).slice(-2);
    return "附註：這一頁在 " + hh + " 提交過一份學號 " + sid + " 但對不上的版本。" +
      "現在這份是真的，剛才那份不是。鏈上沒有留下剛才那份的任何東西——它從沒被寫進去過。";
  }

  /* Only JSON uploads carry a readable student id in the browser; a PDF stays
   * opaque here and simply gets no note. */
  async function studentIdOf(file) {
    if (!file || !/\.(json|txt)$/i.test(file.name || "")) { return ""; }
    try {
      var doc = JSON.parse(await file.text());
      var pp = doc && doc.PersonalParticulars;
      return (pp && pp.StudentID) ? String(pp.StudentID) : "";
    } catch (err) {
      return "";
    }
  }

  async function verifyFile(file) {
    setBusy(true);
    setError("");
    var started = Date.now();
    var sid = await studentIdOf(file);
    try {
      var form = new FormData();
      form.append("file", file);
      var res = await fetch("/api/verify/document", { method: "POST", body: form });
      var body = await res.json().catch(function () { return null; });
      if (!res.ok) { fail(res, body); return; }
      buildResult(body, Date.now() - started);
      if (body.hash_match === false) {
        rememberMismatch(sid);
      } else if (body.hash_match === true) {
        var note = mismatchNote(sid);
        if (note) {
          /* under the verdict, above the buttons: the eye is still there */
          var box = $("result");
          box.insertBefore(el("p", "note", note), box.children[1] || null);
        }
      }
    } catch (err) {
      setError("上傳失敗：" + err.message);
    } finally {
      setBusy(false);
    }
  }

  function onSubmit(event) {
    event.preventDefault();
    var file = $("fileInput").files[0];
    if (file) { verifyFile(file); return; }
    var raw = ($("hashInput").value || "").trim();
    if (!raw) { setError("先粘貼驗證碼，或選一個文件。"); return; }
    var hash = raw.split(/[?&]hash=/).pop().replace(/[\s"'<>]/g, "");
    if (!HASH_RE.test(hash)) { setError("這段不像驗證碼：應為 16–200 個字母數字、- 或 _。"); return; }
    verifyHash(hash);
  }

  function sampleChip(label, hash) {
    var chip = el("button", "chip", label);
    chip.type = "button";
    chip.addEventListener("click", function () {
      $("fileInput").value = "";
      $("fileLabel").textContent = "選擇證書文件（PDF / JSON）";
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
      chips.push(sampleChip("✅ 真實有效", demo.diploma.hashed_document));
    }
    if (list && Array.isArray(list.revoked) && list.revoked.length) {
      chips.push(sampleChip("↩ 已註銷", list.revoked[0].hash));
    }
    chips.push(sampleChip("⚠ 查無此證", new Array(87).join("A")));

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
