# 香港活動卡片（GitHub Pages）

Live: https://burnxwallpaper.github.io/hk-date-cards/

Pages 根目錄直接服務 `index.html` + `app.js` + `style.css` + `data/events.json`。

開發／刷新請見 repo 內 `refresh.py` 與 `scrapers/`。

# 香港活動卡片（個人 MVP）

每週更新嘅公開活動卡片頁，方便揀週末／活動去處。無付款、無廣告、無推播、無同步。

## 點樣用

```bash
cd /workspace/hk-date-cards
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 刷新公開資料 → data/events.json
python refresh.py

# 只寫入手選樣本（無網絡）
python refresh.py --sample-only

# 用本地伺服器睇（要有 HTTP，唔好直接 file://，否則 fetch JSON 可能失敗）
python -m http.server 8765 --bind 127.0.0.1
# 瀏覽器開：http://127.0.0.1:8765/web/
```

## 卡片欄位

| 欄位 | 說明 |
|------|------|
| 標籤 | 場合／氣氛／可選標籤；**卡片最多顯示 1–2 個** |
| 名稱 | 活動標題 |
| 預算 | `免費`／明確金額／**預算未知**（唔會估價） |
| 地點 | 場地字串（地區寫呢度，**唔當 tag**） |

可選資料：日期、來源名、來源 URL。

### 標籤 taxonomy（鎖定）

- **類型（每卡一個；display #1）**：美術館｜展覽｜商場漫遊｜市集｜開放日｜夜景散步｜室內打卡｜長廳｜表演｜戶外走走  
- **場合**：室內｜戶外｜半日｜夜晚｜週末  
- **氣氛**：安靜｜熱鬧｜行路多｜坐低傾  
- **預算 tag（有實據先加；唔入 display_tags）**：免費｜$100內｜$100–300｜$300–600｜$600+  
- **可選**：要早訂｜親子向｜大型公演  

`display_tags` 優先：類型 → 氣氛 → 場合（最多 2）。商場漫遊／長廳／開放日／市集／室內打卡 無付費證據時強制「免費」。音樂會／演唱會→表演（唔好標美術館）；放題／帆船賽唔標戶外走走；商場聯乘→商場漫遊。  
UI 預設篩選：**週末** + **預算 $100內** + **排除親子向**（類型不限）。

## 來源狀況

| 來源 | 結果 | 備註 |
|------|------|------|
| 康文署／香港文化中心「免費文化節目」 | ✅ 可用 | robots 允許；靜態 HTML |
| 新假期 本週末／市集／展覽等文章 | ✅ 可用（best-effort） | 多篇文章表格；slug 轉會 soft-fail |
| 康文署博物館常設免費 | ✅ 可用 | 核對 museum-pass 政策後輸出常設免費場地卡 |
| 旅發局 DiscoverHK events | ✅ 可用 | 解析公開頁內嵌 event JSON；robots 允許 |
| 常設免費場地手選 | ✅ 可用 | 真實官網 URL；Tai Kwun 因 robots Disallow:/ 跳過 |
| Timable | ❌ 跳過 | `User-agent: *` → `Disallow: /` |
| 康文署每月節目表／演藝 e-calendar | ⚠️ soft-skip | JS 渲染，靜態 HTML 無可靠列 |

### ToS／風險（個人用、讀取公開頁）

- 只做 **read-only**、**rate-limit ≥1.5s**、可識別 UA：`HKDateCardsPersonalBot/1.0`。  
- **唔**登入、**唔**繞過付費牆、**唔**打票、**唔**大量鏡像。  
- Timable 已因 robots 跳過。新假期／LCSD 若日後改 ToS 或 HTML，scraper 會 fail soft，保留舊 JSON／樣本。  
- 本工具係個人離線瀏覽；轉發或商業再用前請自行再核來源條款。

## 目錄

```
hk-date-cards/
  refresh.py           # 刷新入口
  requirements.txt
  README.md
  scrapers/
    common.py          # 正規化、類型／標籤、去重、禮貌 GET
    lcsd_free.py
    weekendhk.py
    museums_free.py    # 常設免費博物館
    discoverhk.py      # 旅發局 events JSON
    evergreen_venues.py
    timable.py         # 明確 skip
    lcsd_calendar.py   # soft-skip 探測
  data/
    events.json        # refresh 產出
    sample_events.json # 手選後備
    refresh_log.json
  web/
    index.html
    style.css
    app.js
```

## 去重

以正規化後嘅 **標題 + 日期 + 場地** 合併；合併時保留較明確嘅預算同標籤。

## 已知限制

- HTML 一改，parser 可能拎少咗 → fail soft。  
- 預算只認「免費」或文中明確 `$`／港幣；其餘一律「預算未知」。  
- 場合／氣氛係啟發式，或會漏／誤標；可喺 JSON 人手改 `tags`。  
