"""Build the showcase deck from the current build.

Seven 16:9 slides, real screenshots of the pages as they are after U27, and the
same copy and palette as the A0 poster (poster.html) so the two read as one set.
Text is native, not baked into images, so it stays editable.

Run:  .venv\\Scripts\\python.exe slides_work_v2\\build_deck.py
Out:  P14-Showcase-Deck.pptx
"""

from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

HERE = Path(__file__).resolve().parent
ASSETS = HERE / "poster_assets"
OUT = HERE.parent / "P14-Showcase-Deck.pptx"

INK = RGBColor(0x1A, 0x18, 0x13)
MUTED = RGBColor(0x6B, 0x64, 0x59)
TEAL = RGBColor(0x0F, 0x76, 0x6E)
GOLD = RGBColor(0xA1, 0x62, 0x07)
CREAM = RGBColor(0xF7, 0xF4, 0xEC)
LINE = RGBColor(0xD9, 0xD2, 0xC2)
CARD = RGBColor(0xEF, 0xEA, 0xDD)

FONT = "Microsoft JhengHei"
W, H = Inches(13.333), Inches(7.5)
MARGIN = Inches(0.9)
CONTENT_W = W - 2 * MARGIN


def set_run(run, size, bold=False, color=INK, font=FONT, spacing=None):
    run.font.name = font
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    rpr = run._r.get_or_add_rPr()
    latin = rpr.find(qn("a:latin"))
    if latin is None:
        latin = rpr.makeelement(qn("a:latin"), {})
        rpr.append(latin)
    latin.set("typeface", font)
    ea = rpr.find(qn("a:ea"))
    if ea is None:
        ea = rpr.makeelement(qn("a:ea"), {})
        latin.addnext(ea)
    ea.set("typeface", font)
    if spacing is not None:
        rpr.set("spc", str(int(spacing)))


def text(slide, x, y, w, h, lines, size=14, bold=False, color=INK,
         align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, leading=1.25,
         spacing=None, space_after=0):
    """lines: str, or list of (str, overrides-dict)."""
    box = slide.shapes.add_textbox(x, y, w, h)
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = 0
    tf.margin_right = 0
    tf.margin_top = 0
    tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    if isinstance(lines, str):
        lines = [(lines, {})]
    for i, (line, over) in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = over.get("align", align)
        p.line_spacing = over.get("leading", leading)
        p.space_after = Pt(over.get("space_after", space_after))
        r = p.add_run()
        r.text = line
        set_run(r,
                over.get("size", size),
                over.get("bold", bold),
                over.get("color", color),
                spacing=over.get("spacing", spacing))
    return box


def rule(slide, x, y, w, color=LINE, thickness=0.75):
    bar = slide.shapes.add_shape(1, x, y, w, Emu(int(Pt(thickness))))
    bar.fill.solid()
    bar.fill.fore_color.rgb = color
    bar.line.fill.background()
    bar.shadow.inherit = False
    return bar


def new_slide(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg = s.shapes.add_shape(1, 0, 0, prs.slide_width, prs.slide_height)
    bg.fill.solid()
    bg.fill.fore_color.rgb = CREAM
    bg.line.fill.background()
    bg.shadow.inherit = False
    return s


def header(slide, kicker):
    text(slide, MARGIN, Inches(0.45), Inches(6),
         Inches(0.5), [(kicker, {"size": 10, "color": MUTED, "spacing": 60})])
    rule(slide, MARGIN, Inches(0.85), CONTENT_W)


def footer(slide, note):
    rule(slide, MARGIN, Inches(6.62), CONTENT_W)
    text(slide, MARGIN, Inches(6.75), CONTENT_W, Inches(0.35),
         [(note, {"size": 9, "color": MUTED})])


prs = Presentation()
prs.slide_width = W
prs.slide_height = H

# ---------------------------------------------------------------- 1 cover
s = new_slide(prs)
text(s, MARGIN, Inches(0.55), Inches(6), Inches(0.6),
     [("GEF mobile", {"size": 17, "bold": True}),
      ("Credential Verification Portal", {"size": 10, "color": MUTED})])
text(s, W - MARGIN - Inches(4), Inches(0.55), Inches(4), Inches(0.6),
     [("P14 · GEF26", {"size": 10, "color": MUTED, "align": PP_ALIGN.RIGHT}),
      ("November 2026", {"size": 10, "color": MUTED, "align": PP_ALIGN.RIGHT})])
rule(s, MARGIN, Inches(1.45), CONTENT_W)

text(s, MARGIN, Inches(2.05), CONTENT_W, Inches(0.4),
     [("POST-QUANTUM CREDENTIALS, ON A HASH CHAIN",
       {"size": 11, "color": TEAL, "spacing": 120})])
text(s, MARGIN, Inches(2.45), CONTENT_W, Inches(1.1),
     [("一張證書，四個環節", {"size": 46, "bold": True})])
text(s, MARGIN, Inches(3.55), Inches(9.6), Inches(1.8),
     [("紙本與 PDF 截圖誰都能改，學校網站又只給你看一張圖。",
       {"size": 16, "space_after": 8}),
      ("我們讓每張憑證都帶著機構的簽名、一個上鏈的編號，和一句任何人都查得到的結論。",
       {"size": 16, "space_after": 10}),
      ("簽發、驗證、註銷、再驗 —— 每一步都是一次真的 API 呼叫。",
       {"size": 15, "color": TEAL})])

text(s, MARGIN, Inches(6.15), Inches(8), Inches(0.6),
     [("Yau Ka Chai Johnny · Yu Siu Kui · Yu Yeuk Lan Serena",
       {"size": 11, "bold": True})])
text(s, W - MARGIN - Inches(4.4), Inches(6.15), Inches(4.4), Inches(0.6),
     [("FastAPI · Python · ML-DSA-65", {"size": 9, "color": MUTED,
                                       "align": PP_ALIGN.RIGHT}),
      ("SHA3-512 · hash chain", {"size": 9, "color": MUTED,
                                 "align": PP_ALIGN.RIGHT})])

# ---------------------------------------------------------------- 2 problem
s = new_slide(prs)
header(s, "01 / 問題")
text(s, MARGIN, Inches(1.35), Inches(9.5), Inches(0.9),
     [("一張「看起來很真」的證書，擋不住任何一種偽造",
       {"size": 30, "bold": True})])

rows = [
    ("截圖可以改", "PDF 與紙本上的文字，換一個字、改一個日期，肉眼完全看不出來。"
                   "存成圖片之後，連字型差異都被抹平。"),
    ("單頁不能驗", "學校網站只給你看「某某某於某年畢業」的一頁。"
                   "那一頁是資料庫的轉述，不是憑證本身，也不會告訴你它是不是被撤銷了。"),
    ("撤銷之後查不到", "學生被撤銷學位，紙本還在抽屜裡、PDF 還在舊郵件裡。"
                      "沒有公開的撤銷紀錄，招聘方永遠不知道那份文件已經失效。"),
]
y = Inches(2.55)
for i, (claim, body) in enumerate(rows):
    num = f"0{i + 1}"
    text(s, MARGIN, y, Inches(0.7), Inches(0.4),
         [(num, {"size": 12, "color": GOLD, "bold": True})])
    text(s, MARGIN + Inches(0.75), y - Inches(0.06), Inches(3.2), Inches(0.5),
         [(claim, {"size": 18, "bold": True})])
    text(s, MARGIN + Inches(4.1), y - Inches(0.02), CONTENT_W - Inches(4.1),
         Inches(1.0), [(body, {"size": 13, "color": MUTED})])
    y += Inches(1.28)

footer(s, "P14 · Mobile Credential Verification Portal")

# ---------------------------------------------------------------- 3 four steps
s = new_slide(prs)
header(s, "02 / 四個環節")
text(s, MARGIN, Inches(1.3), Inches(10), Inches(0.8),
     [("一張憑證的一生，從簽發到再驗，全部在同一條鏈上",
       {"size": 26, "bold": True})])

steps = [
    ("01", "簽發", "ISSUING",
     "機構以 ML-DSA-65 加 RSA-PSS 雙簽，寫入一個新的塊。", "新的一個塊 · 14 ms"),
    ("02", "驗證", "VERIFYING",
     "任何人拿驗證碼或 PDF，免註冊，六項檢查一次做完。", "VALID · 10 ms"),
    ("03", "註銷", "REVOKING",
     "追加一條撤銷記錄；PDF 不重簽，簽名本身仍然有效。", "撤銷塊 · 10 ms"),
    ("04", "再驗", "RE-CHECKING",
     "簽名與哈希仍然對得上，但機構說它作廢了 —— 這就是區別。", "REVOKED · 10 ms"),
]
col_w = (CONTENT_W - Inches(0.45)) / 4
x = MARGIN
for num, name, en, body, meta in steps:
    rule(s, x, Inches(2.5), col_w, TEAL, 2)
    text(s, x, Inches(2.65), col_w, Inches(0.3),
         [(num, {"size": 10, "color": GOLD, "bold": True})])
    text(s, x, Inches(2.95), col_w, Inches(0.5),
         [(name, {"size": 22, "bold": True})])
    text(s, x, Inches(3.45), col_w, Inches(0.24),
         [(en, {"size": 9, "color": MUTED, "spacing": 80})])
    text(s, x, Inches(3.8), col_w - Inches(0.15), Inches(1.6),
         [(body, {"size": 12, "leading": 1.35})])
    text(s, x, Inches(4.95), col_w, Inches(0.3),
         [(meta, {"size": 10, "color": GOLD})])
    x += col_w + Inches(0.15)

footer(s, "每一步都是真的 API 呼叫；毫秒數是那次呼叫的實測，不是動畫時長")

# ---------------------------------------------------------------- 4 verify page
s = new_slide(prs)
header(s, "03 / 驗證頁")
pic = s.shapes.add_picture(str(ASSETS / "shot-verify.png"), MARGIN, Inches(1.25),
                           width=Inches(7.1))
pic.left = MARGIN
tx = MARGIN + Inches(7.5)
tw = CONTENT_W - Inches(7.5)
text(s, tx, Inches(1.25), tw, Inches(0.5),
     [("一句結論，四行過程", {"size": 24, "bold": True})])
text(s, tx, Inches(1.85), tw, Inches(4.2), [
    ("輸入驗證碼或上傳 PDF，頁面直接給出 VALID 或 REVOKED，不繞去別的頁面。",
     {"size": 12, "color": MUTED, "space_after": 10}),
    ("結論下面四行，是這次查驗真的做過的事：",
     {"size": 13, "bold": True, "space_after": 6}),
    ("取回鏈上第 N 塊，讀出簽發時間", {"size": 12, "space_after": 4}),
    ("驗證機構的數字簽名", {"size": 12, "space_after": 4}),
    ("比對 PDF 內嵌的哈希", {"size": 12, "space_after": 4}),
    ("查撤銷名單", {"size": 12, "space_after": 10}),
    ("最後一行是整條鏈的完整性，與這次查驗的真實毫秒。",
     {"size": 12, "color": TEAL}),
])
footer(s, "截圖：/ 驗證頁，1440 寬，桌面版")

# ---------------------------------------------------------------- 5 stage page
s = new_slide(prs)
header(s, "04 / 現場舞台")
pic = s.shapes.add_picture(str(ASSETS / "shot-stage.png"), MARGIN, Inches(1.25),
                           width=Inches(7.1))
tx = MARGIN + Inches(7.5)
tw = CONTENT_W - Inches(7.5)
text(s, tx, Inches(1.25), tw, Inches(0.5),
     [("四步各自留下收據", {"size": 24, "bold": True})])
text(s, tx, Inches(1.85), tw, Inches(4.2), [
    ("為 showcase 做的一頁：同一條流程，四個階段，一次跑完。",
     {"size": 12, "color": MUTED, "space_after": 10}),
    ("每一步完成，卡片上就寫下塊號與毫秒數 —— ",
     {"size": 13, "bold": True}),
    ("第 26 塊 · 14 ms", {"size": 13, "color": GOLD, "space_after": 2}),
    ("VALID · 10 ms", {"size": 13, "color": GOLD, "space_after": 2}),
    ("第 27 塊 · 10 ms", {"size": 13, "color": GOLD, "space_after": 2}),
    ("REVOKED · 10 ms", {"size": 13, "color": GOLD, "space_after": 10}),
    ("跑完只留「重來」，右下角的二維碼當場可以掃，看它現在是什麼狀態。",
     {"size": 12, "color": MUTED}),
])
footer(s, "截圖：/showtime 四步跑完的終態")

# ---------------------------------------------------------------- 6 why it holds
s = new_slide(prs)
header(s, "05 / 為什麼站得住")
text(s, MARGIN, Inches(1.3), Inches(7), Inches(0.5),
     [("三件我們不妥協的事", {"size": 26, "bold": True})])
text(s, MARGIN, Inches(2.05), Inches(10.4), Inches(2.5), [
    ("鏈上只存哈希與簽名，姓名與成績永遠不觸鏈。",
     {"size": 15, "space_after": 12}),
    ("憑證 PDF 內嵌署名的載荷，沒有網絡也能驗。",
     {"size": 15, "space_after": 12}),
    ("撤銷走簽名的狀態列表，不是把文件重簽一次。",
     {"size": 15, "space_after": 12}),
    ("六項檢查：簽名、鏈位、哈希、撤銷、簽發方信任、時效。",
     {"size": 15, "color": TEAL}),
])

figs = [("6", "檢查項 CHECKS"), ("2", "簽名方 SIGNERS"),
        ("SHA3-512", "鏈上哈希 ALGO"), ("0", "上鏈的姓名與成績 PII ON CHAIN")]
rule(s, MARGIN, Inches(4.45), CONTENT_W)
fw = CONTENT_W / 4
fx = MARGIN
for big, small in figs:
    text(s, fx, Inches(4.6), fw - Inches(0.2), Inches(0.8),
         [(big, {"size": 26, "bold": True})])
    text(s, fx, Inches(5.3), fw - Inches(0.2), Inches(0.3),
         [(small, {"size": 9, "color": MUTED, "spacing": 40})])
    fx += fw

footer(s, "數字取自 /healthz 與 /api/verify 的實際回傳；收據是 11 月 27 日一次真實運行的實測")

# ---------------------------------------------------------------- 7 codes
s = new_slide(prs)
header(s, "06 / 現在，掃一下")
text(s, MARGIN, Inches(1.25), Inches(8), Inches(0.6),
     [("兩枚二維碼，一個看流程，一個看源碼", {"size": 26, "bold": True})])

for i, (png, cap, url) in enumerate([
        ("qr-youtube.png", "掃碼看 2 分鐘演示", "youtu.be/nVgevH43FYA"),
        ("qr-github.png", "掃碼看源碼", "github.com/JohnnyYau/gef-mobile-credential-portal")]):
    x = MARGIN + i * Inches(4.4)
    s.shapes.add_picture(str(ASSETS / png), x, Inches(2.15), width=Inches(2.5))
    text(s, x, Inches(4.85), Inches(3.4), Inches(0.9),
         [(cap, {"size": 13, "bold": True, "space_after": 2}),
          (url, {"size": 10, "color": MUTED})])

text(s, MARGIN + Inches(8.9), Inches(2.3), Inches(3.2), Inches(2.6), [
    ("現場也開著一個網址，", {"size": 12, "color": MUTED}),
    ("隨手就能自己驗一次。", {"size": 12, "color": MUTED,
                              "space_after": 10}),
    ("掃左邊那枚，看完整流程；", {"size": 12}),
    ("掃右邊那枚，看它怎麼做出來的。", {"size": 12}),
])

footer(s, "Yau Ka Chai Johnny · Yu Siu Kui · Yu Yeuk Lan Serena · GEF mobile · P14")

# ---------------------------------------------------------------- speaker notes
# What to say, not what to read: the slides are already on the wall. Written so
# that any of the three of us can open the deck cold and sound like ourselves.
NOTES = [
    "開場就講一句：紙本和 PDF 截圖誰都能改，學校網站又只給你看一張圖。\n"
    "所以我們做的不是另一個文憑驗證網站，而是把「這一刻，這張憑證有沒有被動過」"
    "變成一個任何人按一次就有的答案。\n"
    "若被問技術棧：FastAPI，簽名用 ML-DSA-65（後量子）與 RSA-PSS 並存，鏈用 SHA3-512。",

    "三件事，每件都指一下對應那格。\n"
    "第三點最少人講：一張 2019 年發的文憑，2023 年被撤銷了，你手上那份 PDF 完全看不出來——"
    "因為「撤銷」這件事沒有寫在任何你看得到的地方。",

    "簽發、驗證、註銷、再驗。指每張卡右下那行小字：那是真的 API 呼叫量到的毫秒，不是動畫。\n"
    "第 1 塊簽發、第 3 塊撤銷：同一個人在同一條鏈上留下兩筆，第二筆說第一筆不算了。",

    "這是一個真的僱主會看到的畫面。上面一句結論，下面四行說明它憑什麼這樣說："
    "取回鏈上第 N 塊、用機構公鑰驗簽、比對內容雜湊、查撤銷名單。\n"
    "四行裡任何一行不通過，上面就不會是綠色——這是我們刻意不讓它「只給一句話」。",

    "這是我們在台上用的同一頁。四步跑完，四張收據都寫著塊號與毫秒。\n"
    "為什麼要在台上跑真的？因為假的一被問「第幾塊」就露了；而我們每一格都答得出來。",

    "三條原則：只用後量子簽名（ML-DSA-65 與 RSA-PSS 並存、簽名方可輪替）；"
    "鏈上只有雜湊與簽名；結論只說「這一刻、這六項檢查通過」。\n"
    "右上那個 0 是我們最在意的數字：鏈上沒有一筆姓名或成績。\n"
    "若被問法律效力：我們不宣稱它是學歷認證，只宣稱這一刻的密碼學結論——"
    "這句話就印在每張收據上。",

    "兩枚碼：左邊是完整的四步錄屏，右邊是原始碼。\n"
    "網址是臨時的，碼不是——所以我們印的是碼，不是那一串 trycloudflare。\n"
    "收尾一句：你現在可以掃，也可以回去自己起一份。",
]

for _slide, _note in zip(prs.slides, NOTES):
    _slide.notes_slide.notes_text_frame.text = _note

prs.save(OUT)
print(f"{OUT.name}  {OUT.stat().st_size / 1e6:.2f} MB  {len(prs.slides.__iter__.__self__._sldIdLst)} slides")
