# 純網頁在線檢查實測

日期：2026-10-17。僅針對公開版 Service Harbor，在臨時資料、loopback 測試端點及獨立 Dashboard 程序驗證。未修改私人版本、正式環境檔、既有 SSH key 或正式 systemd 單元，未安裝套件。

## 驗證範圍

| 項目 | 實際驗證方式與結果 |
| --- | --- |
| HTTP | 真實本機 HTTP server 回傳 200、204、301、302、401、403 為 Running；404、429、500、503 為 Stopped；含時間及狀態碼。 |
| 不追蹤轉址／下載內容 | 302 的目的端點沒有收到請求；宣告 100 MB 但不傳 body 的端點仍立即完成。請求未帶 Cookie 或 Authorization。 |
| HTTPS | 臨時測試 CA + 正確 localhost 名稱成功；同張憑證改用 IP 名稱失配、未信任該 CA 均拒絕連線，顯示 Stopped。沒有略過憑證驗證。 |
| TCP | 真實 TCP listener 與 URL 推導目標可連通；未監聽的 Port 顯示 Stopped 與原因。 |
| 逾時／Disabled | 延遲端點觸發 socket timeout；Disabled 完全不連網。缺少 host／port、無效 method、錯誤型別與非法地址被拒絕。 |
| 真實 API | 臨時 Uvicorn + HTTP 登入 session，新增 HTTP、查 Live／Status、改成 TCP。無 unit 項目拒絕 Start／Stop／Restart 和 journal。 |
| 舊資料／設定 JSON | 讀取缺 website_check 的舊服務不改寫原檔、不探測；TCP 設定匯出／匯入保留。舊 JSON 無新欄位時預設 Disabled。 |
| Chrome | 實際填寫新增、編輯與切換 HTTP／TCP／HTTPS／Disabled；核對名稱預填、Status／最後檢查時間、無控制與 Log、無未捕捉的頁面錯誤。 |
| Live／鈴鐺 | 記錄瀏覽器請求時間，驗證約三秒選取輪詢與五秒限時追蹤，沒有純網頁 journal 請求。關頁停止，重開保留原絕對到期時間並恢復；再次點鈴鐺停止。 |
| 手機版 | 390 × 844 Chrome viewport，Services 無水平溢出；桌面為 1440 × 1000。 |
| 保留既有內容更新 | 在 TemporaryDirectory 真正 clone 本地 repository，切至已發布舊版 248dd03，填入虛構 data、Hosts、session、SSH key、.env、.venv、未追蹤筆記，再執行 git pull --ff-only origin main，逐檔確認內容不變、程式更新。安裝目錄外的虛構 dashboard.env 也不變。 |

## 實測中修正

1. 純網頁 drawer 同時發出 Status 與 Live 探測，可能重複連線及讓舊 Status 覆蓋新結果。改為使用單項 Live 快照顯示詳情；Node 回歸先確認舊行為失敗，再驗證無額外 Status／Log 請求。
2. 編輯視窗原本延遲 30 ms 聚焦名稱，快速操作其他欄位時可能被搶走焦點。改為開窗時同步聚焦；Node 回歸驗證焦點立即正確且不會稍後從 URL 欄位被移走。
3. 更新 Once added to Services 中舊的 link-only 提示，說明可選在線檢查。

## 最終結果

- Python 全套：108 項通過（包含新增 7 項實際網路／API 檢查及 1 項 Git 更新保留資料檢查）。
- Node 前端全套：20 項通過（新增重複探測與焦點回歸）。
- Chrome 完整情境：通過；最後一輪 Live 間隔為 3000、3000 ms，鈴鐺追蹤間隔 5000 ms，未捕捉頁面錯誤為 0。
- Python 語法、app.js／Chrome 腳本語法及 git diff --check 通過。
- 本次使用既有 FastAPI runtime 有 on_event deprecated 提示，不影響上述結果；尚未在此次改動中更換啟動生命週期 API。

## 重跑

使用專案自己的 Python 測試環境（下方 `.venv/bin/python`）。實際驗證借用主機已存在的 Python runtime 與 Playwright 套件，沒有修改那些專案。應用程式不需要 Node、Playwright 或 OpenSSL CLI；只有本次 Chrome／臨時 TLS fixture 測試需要。

```bash
.venv/bin/python -m unittest discover -s tests -q
node --test tests/*.test.cjs
```

Chrome 測試需要已安裝的 Google Chrome、Playwright、OpenSSL CLI，使用兩個終端：

```bash
# 終端 1：請先確認 18769 未被使用；固定測試密碼只用於臨時 fixture。
PYTHONPATH=. .venv/bin/python tests/website_fixture.py --port 18769 > /tmp/service-harbor-website-fixture.log 2>&1
```

```bash
# 終端 2：如 Playwright 不在 Node 標準搜尋路徑，可設定其模組路徑。
PLAYWRIGHT_MODULE=/path/to/node_modules/playwright node tests/website-browser.cjs
```

結束後在終端 1 按 Ctrl+C。Fixture 以 0.0.0.0 綁定獨立臨時 Dashboard（測試密碼 `isolated-browser-only`），測試服務端點只綁 loopback。所有主機、服務與憑證都是虛構測試資料；不要指向正式 Dashboard。瀏覽器截圖寫入 `/tmp/service-harbor-add-website.png`、`/tmp/service-harbor-website-tracking.png`、`/tmp/service-harbor-website-mobile.png`，不納入 Git。

## 尚未驗證

本次未執行全新 Ubuntu 的安裝／reset／uninstall／重新開機，也未驗證真實跨機網路、防火牆、代理、公開網站或非 Chrome 瀏覽器。Git 更新使用真實 Git 與本地來源，沒有透過 GitHub 網路傳輸；有本地程式修改、分支分歧或衝突時依維運文件停止並人工處理，不能宣稱自動保留任意追蹤檔的衝突內容。Socket timeout 不涵蓋所有作業系統 DNS 解析延遲。HTTP Running 表示已取得符合規則的回應，不等於網站業務功能正常。
