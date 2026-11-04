# 全球財經政治日報

每天台灣時間早上 6:20 自動抓取全球約 50 個財經與政治新聞來源，合併重複報導、分類、翻譯、摘要，產生一個手機優先的單頁工作台。

## 架構

```
GitHub Actions（每天排程）
  └─ fetch.py
       1. 抓 sources.json 裡的 RSS（單一來源失敗不影響其他）
       2. 過濾 36 小時前的舊聞、體育娛樂雜訊
       3. 標題相似的新聞合併成同一事件
       4. 依關鍵字分地區 / 主題，依「幾家報導 + 主題 + 新舊」打分數，保留前 200 則
       5. AI 摘要：GitHub Models（免費，用內建 GITHUB_TOKEN，不需要 API key）
          └─ 失敗時退回 Google 機器翻譯 → 再失敗就顯示原文
       6. 輸出 docs/data/YYYY-MM-DD.json
  └─ commit 回 repo → GitHub Pages 自動更新
docs/index.html + app.js + style.css   ← 前端，直接讀 docs/data/ 的 JSON
```

## 第一次啟用（只要做一次）

1. **GitHub Pages**：repo 的 Settings → Pages → Source 選 `Deploy from a branch`，Branch 選 `main`、資料夾 `/docs` → Save。
   網址：https://anitakuo0320-dot.github.io/news/
2. **手動跑第一次**：Actions 分頁 → 左邊選「每日新聞抓取」→ 右邊 `Run workflow`。約 3~5 分鐘完成。
   若卡在 push 權限錯誤：Settings → Actions → General → Workflow permissions 選 `Read and write permissions`。
3. **手機加到主畫面**：用 Safari / Chrome 打開網址 → 分享 → 加入主畫面。

## 常見操作

### 新增或移除新聞來源
編輯 `sources.json`：

```json
{"name": "顯示名稱", "url": "RSS 網址", "region": "us", "limit": 15, "enabled": true}
```

- `region`：us / europe / china / japan / asia / mideast / latam / global
- `limit`：每次最多收幾則
- 暫停某個來源：`enabled` 改成 `false`
- 找不到 RSS 的網站，可以用 Google News 轉接：
  `https://news.google.com/rss/search?q=site:網域+when:1d&hl=en-US&gl=US&ceid=US:en`
- 檢查某個來源有沒有成功：頁面最下方「來源狀態」

### 手動觸發更新
Actions → 每日新聞抓取 → Run workflow。

### 改排程時間
編輯 `.github/workflows/news.yml` 的 `cron`。時間是 **UTC**，台灣時間減 8 小時。
例：台灣 07:00 → UTC 23:00 → `"0 23 * * *"`

### 調整分類或重點挑選
`fetch.py` 開頭的 `REGION_KEYWORDS`、`TOPIC_KEYWORDS`、`TOPIC_WEIGHT`。

### 本機測試
```bash
pip install feedparser
NEWS_AI=0 python fetch.py   # NEWS_AI=0 代表不呼叫 AI
python -m http.server -d docs   # 打開 http://localhost:8000
```

## 來源替換紀錄

| 原本想要 | 狀況 | 改用 |
|---|---|---|
| Reuters | 2020 年起停用公開 RSS | Google News 轉接 `site:reuters.com` |
| AP | 沒有官方 RSS | Google News 轉接 `site:apnews.com` |
| 財新 Caixin | RSS 擋爬蟲（403） | Google News 轉接 |
| 共同社 Kyodo | RSS 已下線（404） | Google News 轉接 |
| 鉅亨網 | 沒有 RSS | 鉅亨網公開 JSON API |
| Focus Taiwan | RSS 404 | Google News 轉接 |
| Arab News / IMF | RSS 擋爬蟲（403） | Google News 轉接 |
| 中國日報 | RSS 404 | 改用 CGTN 商業 |
| — | 新增 | Bloomberg、FT、Economist、WSJ 市場（標題與摘要免費）、BoE、BOJ |

CNBC、NPR、Times of Israel、Americas Quarterly 在部分網路環境會被擋，程式會自動略過並在頁面標示。

## 限制

- 只存標題、短摘要與連結，不轉載全文。
- 合併同一事件靠標題相似度，跨語言（中英文報導同一件事）不會合併。
- AI 與機器翻譯可能翻錯數字、人名，做判斷前請點原文。
- GitHub Models 免費額度有每日上限；超過時當天會自動改用機器翻譯，沒有「為什麼重要」那一句。
