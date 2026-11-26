// Sync assertions, evaluated inside the portal realm loaded by harness.mjs.
// Every check targets a real XSS path the audit found, not a synthetic case.

const EVIL = '<img src=x onerror="alert(1)">';

// 1. pure escaping (core.js)
assert(escapeHtml(EVIL) === "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;",
  "escapeHtml should neutralise a full tag with a quoted handler");
assert(escapeHtml("<script>") === "&lt;script&gt;", "escapeHtml should escape angle brackets");
assert(escapeHtml("a & b") === "a &amp; b", "escapeHtml should escape ampersands");
assert(escapeHtml("it's") === "it&#39;s", "escapeHtml should escape single quotes");
assert(escapeHtml(null) === "" && escapeHtml(undefined) === "",
  "escapeHtml should map null/undefined to empty string");
assert(escapeHtml(0) === "0", "escapeHtml should keep falsy-but-real values");
assert(esc("<b>") === escapeHtml("<b>"), "esc must delegate to escapeHtml");

// 2. verdict shaping (format.js)
assert(verdictZh("VALID") === "真实有效", "verdictZh should translate VALID");
assert(verdictZh("VALID ON CHAIN") === "真实有效", "verdictZh should translate VALID ON CHAIN");
assert(verdictEn("VALID ON CHAIN") === "VALID", "verdictEn should fold VALID ON CHAIN");
assert(verdictZh(null) === "—", "verdictZh should fall back to a dash");
assert(chipFor("<b>x</b>").indexOf("<b>x</b>") === -1, "chipFor should not pass raw markup through");

// 3. holder card (renderHolder) — student supplied names
renderHolder({
  PersonalParticulars: { Surname: EVIL, GivenNames: "A", StudentID: '<svg onload="x">' },
  AcademicInfo: { DegreeName: "BSc" },
  DocumentInfo: { IssuingO: "U", IssuingOU: "CS", DocType: "Diploma", DateOfIssue: "2026-01-01" },
});
const holderHtml = document.getElementById("holderTable").innerHTML;
assert(holderHtml.indexOf("<img") === -1, "renderHolder must not emit a raw <img>");
assert(holderHtml.indexOf("&lt;img") !== -1, "renderHolder must emit escaped entities instead");

// 4. batch verify result (verify.js) — server echoes the row's input
renderBatch({
  summary: { total: 2, valid: 1 },
  results: [
    { row: EVIL, hashed_document: "abc<!>", verdict: "NOT FOUND", error: EVIL },
    { row: 2, hashed_document: "def", verdict: "VALID ON CHAIN", receipt_id: EVIL },
  ],
});
const batchHtml = document.getElementById("batchOut").innerHTML;
assert(batchHtml.indexOf("<img") === -1, "renderBatch must not emit a raw <img> from row data");
assert(batchHtml.indexOf("&lt;img") !== -1, "renderBatch must escape the injected row");

// 5. question holder card + web sources (chat.js)
const personHtml = personCard({
  name: EVIL,
  student_id_masked: "****1234",
  verdict: 'VALID ON CHAIN" onmouseover="alert(1)',
  hash_prefix: "abc",
  credential: { doc_type: "Diploma", degree: "BSc" },
});
assert(personHtml.indexOf("<img") === -1, "personCard must escape the person name");
assert(personHtml.indexOf('onmouseover="alert(1)"') === -1,
  "personCard must escape the verdict before it reaches an attribute");
const webHtml = webCard({
  status: "ok",
  sources: [{ url: 'javascript:alert(1)', title: EVIL, snippet: EVIL }],
});
assert(webHtml.indexOf("<img") === -1, "webCard must escape titles and snippets");
assert(webHtml.indexOf("&lt;img") !== -1, "webCard must escape the injected title");

// 6. receipt HTML (format.js)
const receipt = receiptHtml({
  verdict: "VALID", hashed_document: EVIL, receipt_id: EVIL,
  chain_integrity: true, signer_trusted: true, on_chain_record: true,
  hash_match: true, signature_valid: true, not_revoked: true,
});
assert(receipt.indexOf("<img src=x") === -1, "receiptHtml must escape the hash and receipt id");

// 7. CSV import shaping (registrar.js) — the wizard's parsing layer
const parsed = parseCsv('surname,given_names,student_id,degree\r\n"CHAN, Tai","Man <b>",123456,"BSc"');
assert(parsed.length === 2, "parseCsv should return a header row plus one data row");
assert(parsed[1][0] === "CHAN, Tai", "parseCsv should keep a comma inside quotes");
assert(parsed[1][1] === "Man <b>", "parseCsv should preserve text verbatim (escaping happens at render)");
const creds = csvToCredentials('surname,given_names,student_id,degree\nevil,<i>x</i>,1,BSc', "Demo University");
assert(creds.length === 1, "csvToCredentials should emit one row");
assert(creds[0].item || creds[0].error, "csvToCredentials rows must be item-or-error shaped");
