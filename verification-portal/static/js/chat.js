// chat.js - RAG chat: messages, person/web cards, suggestions
"use strict";

// ---- chat ----
// NOTE (U6.2): this is the one sink that intentionally takes markup, because a
// chat bubble composes a card, an answer and a source list. Every caller passes
// only server-independent fragments built here, and every server string inside
// them goes through esc() first (answer, generator, model, person card, web
// sources, source list). Do not call it with a raw API string.
function addChatMsg(html, cls) {
  const div = document.createElement("div");
  div.className = "msg " + cls;
  div.innerHTML = html;
  $("chatlog").appendChild(div);
  $("chatlog").scrollTop = $("chatlog").scrollHeight;
  return div;
}
function sourceList(sources) {
  if (!sources || !sources.length) return "";
  const items = sources.map((s) => {
    const tag = s.id
      + (s.height !== undefined ? " · height " + s.height : "")
      + (s.action ? " · " + s.action : "")
      + (s.score !== undefined ? " · score " + s.score : "");
    return "<li><span class=\"tag\">" + esc(tag) + "</span><br>" + esc(s.text) + "</li>";
  }).join("");
  return "<div class=\"srcs\"><details><summary>来源 Sources (" + sources.length + ")</summary><ul>" + items + "</ul></details></div>";
}
function chatSid() {
  let sid = localStorage.getItem("chat.sid");
  if (!sid) {
    sid = Math.random().toString(36).slice(2) + Date.now().toString(36);
    localStorage.setItem("chat.sid", sid);
  }
  return sid;
}
function personCard(p) {
  if (!p) return "";
  const c = p.credential || {};
  const cls = p.verdict === "VALID ON CHAIN" ? "ok" : (p.verdict === "REVOKED" ? "bad" : "warn");
  const rows = [
    ["姓名 Name", p.name], ["学号 Student ID", p.student_id_masked],
    ["凭证类型 Document", c.doc_type], ["学位 Degree", c.degree],
    ["起止 Dates", c.start + " – " + c.end], ["荣誉 Honour", c.honour],
    ["签发方 Issued by", c.issuing_org + (c.issuing_ou ? " / " + c.issuing_ou : "")],
    ["签发日期 Issued on", c.issued_on],
    ["状态 Status", p.verdict + (p.issued_height ? " · height " + p.issued_height : "")],
    ["凭证编号 Hash", p.hash_prefix + "…"],
  ].filter(r => r[1] !== undefined && r[1] !== null && String(r[1]).trim() !== "");
  const rowsHtml = rows.map(r => "<tr><td>" + esc(r[0]) + "</td><td>" + esc(r[1]) + "</td></tr>").join("");
  return "<div class=\"pcard\"><div class=\"pcard-h\"><span>当前人物 Person in context</span>"
    + "<span class=\"vchip " + cls + "\">" + esc(p.verdict) + "</span></div>"
    + "<table>" + rowsHtml + "</table>"
    + "<button class=\"btn mini\" data-web=\"" + esc(p.name) + "\">搜索此人公开信息 Search the web</button></div>";
}
function webCard(w) {
  if (!w) return "";
  if (w.status !== "ok") {
    return "<div class=\"webcard off\"><b>网络检索 Web research</b> — " + esc(w.reason || "unavailable") + "</div>";
  }
  const demo = w.demo ? " <span class=\"demobadge\">DEMO DATA</span>" : "";
  const items = (w.sources || []).map(s =>
    "<li><a href=\"" + esc(s.url) + "\" target=\"_blank\" rel=\"noopener noreferrer\">" + esc(s.title) + "</a>"
    + (s.sample ? " <span class=\"demobadge\">sample</span>" : "")
    + "<br><span class=\"muted\">" + esc(s.snippet) + "</span></li>").join("");
  return "<div class=\"webcard\"><div class=\"pcard-h\"><span>公开来源 Public sources</span>" + demo + "</div>"
    + "<ul>" + items + "</ul>"
    + (w.note ? "<div class=\"muted\">" + esc(w.note) + "</div>" : "") + "</div>";
}
async function sendChat(q, opts) {
  const question = (q || $("chatinput").value).trim();
  if (!question) return;
  $("chatinput").value = "";
  addChatMsg(esc(question), "user");
  const thinking = addChatMsg("思考中…", "thinking");
  try {
    const res = await api("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, session_id: chatSid(), web: !!(opts && opts.web) }),
    });
    thinking.remove();
    const meta = "由 " + esc(res.generator)
      + (res.model ? " (" + esc(res.model) + ")" : "")
      + (res.retrieval ? " · " + res.retrieval.hits + " 条检索 · 最高分 " + res.retrieval.top_score : "");
    addChatMsg(personCard(res.person) + esc(res.answer) + webCard(res.web)
      + sourceList(res.sources) + "<div class=\"meta\">" + meta + "</div>", "ai");
  } catch (e) {
    thinking.remove();
    addChatMsg("错误: " + esc(e.message), "ai");
  }
}
async function loadSuggestions() {
  try {
    const s = await api("/api/chat/suggestions");
    const box = $("chips");
    box.innerHTML = "";
    (s.suggestions || []).forEach((q) => {
      const b = document.createElement("button");
      b.className = "chipq";
      b.textContent = q;
      b.addEventListener("click", () => sendChat(q));
      box.appendChild(b);
    });
  } catch (e) { /* suggestions unavailable */ }
}
async function loadGenHint() {
  try {
    const st = await api("/api/rag/status");
    $("genHint").textContent = st.generator + " · 嵌入: " + st.embedder + " · " + st.index_entries + " 条记录";
  } catch (e) { $("genHint").textContent = "unavailable"; }
}
$("chatSend").addEventListener("click", () => sendChat());
$("chatinput").addEventListener("keydown", (e) => { if (e.key === "Enter") sendChat(); });
$("chatlog").addEventListener("click", (e) => {
  const b = e.target.closest("[data-web]");
  if (b) sendChat("Search the web for " + b.getAttribute("data-web"), { web: true });
});
const holderInput = $("holderlink");
if (holderInput) holderInput.addEventListener("keydown", (e) => { if (e.key === "Enter") openHolder(); });
