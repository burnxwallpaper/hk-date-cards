# 香港約會卡片（個人 MVP）

公開活動精簡卡：tag｜名｜預算｜地點。無付款、無廣告、無推播。

**線上：** https://burnxwallpaper.github.io/hk-date-cards/

## 本機

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python refresh.py
python -m http.server 8765 --bind 127.0.0.1
# http://127.0.0.1:8765/
```

## 來源

- 康文署／香港文化中心免費節目（可用）
- 新假期公開表（best-effort）
- Timable：robots.txt Disallow → 唔爬

刷新後 commit `data/events.json` 即更新 GitHub Pages。
