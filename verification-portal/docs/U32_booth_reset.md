# U32 — 開攤前重置：一條乾淨的鏈

日期：2026-11-27

## 為什麼要清

舊鏈已經長到 66 塊，裡面有十幾張測試簽發（`CHAN Tai Man`、`TIMING PROBE`，還有一張
`TIMING PROBE` 的殘留）。台上說「第 4 塊」之前，觀眾會先看到「鏈上 66 塊 · 誰簽的」，
而裡面有一半是我們自己 debug 寫的。清掉之後，開場第 1 塊是新的學位憑證，觀眾看到
的每一塊都有意義。

## 做了什麼

- `data/demo-chain/` 連同 `receipts.json`、`revocation-index.json`、`public-log.jsonl`、
  `audit-log.jsonl`、`notifications.jsonl` 一起移到 `data/archive-20261127/`（1.8 MB，
  可回滾，沒有刪除）。`apikeys.json` 與 `rag-cache` 留著。
- 重啟服務 → `ensure_chain()` 重新寫 genesis、簽發 demo 文憑與成績單（第 1、2 塊）。
- 用 `POST /api/signers` 補回第二把簽名鑰匙（`REGISTRAR OFFICE` / RSA-PSS-2048），
  海報上的「2 SIGNERS」才對得上；主簽仍是 ML-DSA-65。
- 跑一次完整演示（`/showtime?auto=1`），留下第 3 塊簽發、第 4 塊簽發、第 5 塊撤銷。
  截圖就是這一次的四態。

現在：`height 5`、`2 signers`、`integrity ok`。

## preflight 順手修的一個死結

`c_revoked()` 原本寫死一個舊的撤銷雜湊。鏈一清，那張憑證就不存在，於是檢查報
`KeyError: 'reason'` —— 產品沒問題，測試在說謊。改成掃本機 `data/demo-chain/blocks`
找**最新的一筆 REVOKE**，拿它的 `HashedDocument` 去驗；掃不到才回落常數。

驗證：`11/11 checks passed`，撤銷原因讀到「在展示現場當場撤銷（演示）」。

## 新增物料

- `P14-Booth-Cheat-Sheet.pdf`（A4 兩頁）
  - 第 1 頁：代碼怎麼講。一張憑證的一生四步、檔案地圖（行號）、三個必答的「為什麼」、
    用詞紅線（不准說 blockchain）。
  - 第 2 頁：現場怎麼跑。30 秒開場、90 秒四張卡、六條評審問題、四種故障處置、三條紅線。

## 仍開著

- 海報上的 14 ms / 10 ms 是安靜機器、27 塊時量的；台上會是幾百毫秒。講的時候先說
  「這個數字會隨機器負載浮動」。
- 官方展覽頁那三處（GitHub 404、舊海報、blockchain 摘要）仍然未動，等指示。
