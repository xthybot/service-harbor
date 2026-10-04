# AGENTS.md — 開發與維運操作指南

本指南供在此 repository 工作的程式代理與維護者使用。使用者當前的明確授權與限制優先。以繁體中文說明修改目的、部署位置、驗證證據及尚未驗證項目。

## 專案與入口

此專案是一般帳號執行的 FastAPI Dashboard。裝置收集器與獨立監控網站的原始碼位於 `~/host-device-monitor`；公開預設只含 Dashboard；另裝 monitor 後需透過 Add service 註冊卡片，system 控制需精確 sudoers。沒有前端 build、資料庫或 Node runtime 依賴。先讀 README.md 與 docs/ 下的安裝、設定、架構、維運、監控和 SSH 主機指南。公開版不包含私有歷史的 `docs/superpowers/`；以現行程式、TASKS.md 與 docs 為準。

建議部署目錄為 `~/host-service-dashboard`，預設綁定 0.0.0.0:8765。分享安裝可自選路徑、IP、Port 及 user/system 模式，依私密 install.json 與實際 unit 判斷。實際執行設定在 `~/.config/host-service-dashboard/dashboard.env`，不是 repo 的 .env.example。Python 相依套件在 .venv。外部單元可能是正式服務，修改操作會影響使用者。

## 工作前盤點

- 看 git status、diff、remote 與目前分支，確認 repository 與公開狀態。開發前建立並切換新分支；驗證通過後合併至本機 main。保存使用者未提交的修改，不做 reset --hard 或強制推送。只有使用者要求推送時才使用 `gh` 處理 GitHub 操作，透過 SSH 執行 git push。
- 讀變更相關模組和 systemd 範本，確認原始碼與實際安裝檔差異。
- 文件／備份工作不需要重啟網站；Python 行為修改後，正式部署時需依安裝模式重啟；未獲授權時只做隔離驗證。純靜態檔由服務直接讀取，但瀏覽器需載入新版資源。
- 維持簡單架構與既有 responsive 視覺；側邊欄字級與大小有使用者既定要求，不應跟隨主內容字級任意放大。

## 不可破壞的界線

- Dashboard 絕不以 root 執行。system unit 控制必須經 catalog allowlist 與確切 sudoers 命令，禁止萬用字元、任意 unit 或任意 shell。
- API 用 subprocess argument list、timeout 與日誌行數上限；不得接受使用者提供的 shell 字串。
- 資料 API 保留 session 驗證，寫入保留 Origin 同源檢查。cookie 七天、HttpOnly、SameSite=Strict。密碼變更不會自動撤銷 session，撤銷流程見維運文件。
- 不讀出或印出密碼、cookie、session token。不要把環境檔、data/、journal、備份、.venv 推送到 GitHub；私人 repository 也適用。
- KEY_POWER monitor 不記錄普通鍵盤／滑鼠事件，不擷取畫面，不修改電源鍵關機行為，不使用 grab。不要為驗證按實體電源鍵。
- 動態發現 event nodes，不依賴 event 編號固定。by-id／by-path 可以不存在或在熱插拔時消失；Path.iterdir 的實際迭代必須處於例外處理之內。
- 新增系統套件前先告知使用者套件名稱與原因，未獲授權不安裝；monitor 預設只用標準函式庫。

## 修改對照

- 新服務：內建 app/catalog.py；UI 註冊 app/registry.py + data/registered-services.json。內建服務可編輯的分類／描述覆寫在 data/service-metadata.json；Host、scope、unit 固定。system scope 必須對照服務所屬主機的精確 sudoers，Web 不自動授權。
- Port：app/manual_ports.py、app/service_ports.py 與 data/manual-ports.json／data/service-ports.json；手動及服務已設定 Port 均由 Dashboard 主機做 TCP 連線檢查，不透過 SSH／sudo 執行 Port 命令。不可把連通結果解讀成 HTTP 健康狀態或特定 unit 健康狀態；systemd 狀態另外在 Services 顯示。刪除已被手動 Port 引用的 Hosts 主機會被拒絕，應先移除其 Port 紀錄。
- 服務設定 JSON：app/config_transfer.py + app/static/config-transfer.js。匯出可選全部／類別／最愛／手動新增／單一服務，不可含主機顯示名稱、SSH key、known_hosts、指紋、密碼或 session。匯入先預覽並明確選擇覆蓋或跳過重複服務；遠端主機以位址＋使用者＋SSH Port 對應，不同 Port 建新主機，信任狀態絕不從 JSON 還原。
- SSH：app/ssh_hosts.py + hosts.js。私鑰只在 data/ssh，不送 API／Git；只允許固定非互動指令，保留 StrictHostKeyChecking、BatchMode、無 PTY／stdin／forwarding。掃描 fingerprint 必須獨立核對後手動信任。
- 本機與不同遠端主機可有同名 unit，路由使用 svc-UUID，執行使用 entry.unit；勿誤將新服務 ID 當 unit。External links 顯示 Linked，連線錯誤顯示 Unavailable，不提供外部 URL 的遠端控制／journal。
- UI：app/static/index.html、app.js、styles.css；新增頁面同步 hash routing、nav、隱藏／顯示、SSE lifecycle、空資料和錯誤狀態。Services 的 systemd 資料與 Open ports 的 TCP 結果必須維持分離。來自 Services 的 Port 在 Open ports 只能查看，右上角 View service 要開啟對應的 Services 詳情；修改或移除該 Port 走 Services 編輯。手動 Port 可在 Open ports 編輯／刪除。
- 別名／URL／最愛：對應 service_names.py、service_urls.py、service_favorites.py；保持 JSON 原子寫入與私密權限。
- 限時追蹤：tracking.js 以瀏覽器保存絕對到期時間，僅登入且頁面開啟時查詢；服務與其 Port 共用追蹤。app.js trackingCheck 沿用單項 API 與 journal 權限。不得加入後端常駐排程或持久化 Log；手動 Port 只查 TCP。
- Overview：overview.js／overview.css 接收 app.js 的 dashboard:inventory 及 Hosts 事件。首頁不新增背景輪詢或虛構健康狀態；區分服務 Failed、查詢 Unavailable 與 TCP Unreachable，Stopped 不列為異常。保留各項檢查時間和初始載入／失敗狀態。首頁搜尋使用已載入資料；完整 scope／最愛篩選位於 Services。
- Monitor：原始碼位於 `~/host-device-monitor/monitor/host_device_monitor.py`；執行的是 `/usr/local/lib/host-device-monitor/host_device_monitor.py`，repo 修改後單純 restart 不會更新它。
- Port／路徑：範本與已安裝 unit、文件、footer、防火牆設定要一致；先辨識對現行服務的影響。
- 前端資源修改後更新 index.html 的版本 query，保證瀏覽器取得新 JS／CSS。頂端 Not live／Live 只控制選取服務或 Port 的三秒輪詢；Log SSE 由 Log 自己的 Pause／Resume 控制，勿混為一談。

## 驗證與部署

以變更風險選擇有意義的檢查，不為純文件修改重啟正式服務。除非使用者要求，不新增或執行測試；可做語法、文件一致性與唯讀服務狀態檢查。文件變更至少核對指令與實際模組、路徑、API、權限，並執行 `git diff --check`。程式修改可使用語法檢查：

```bash
node --check app/static/app.js
bash -n scripts/setup.sh
python3 -c 'from pathlib import Path; [compile(p.read_text(), str(p), "exec") for p in Path("app").rglob("*.py")]'
```

Node 只用於開發語法檢查，不是部署必需品。systemd-analyze verify 可檢查單元格式，但 user unit 的 %h 解析與實際安裝路徑可能造成非正式環境警告，應辨別原因。

Dashboard 部署：user 模式 `systemctl --user restart host-service-dashboard.service`，system 模式 `sudo systemctl restart host-service-dashboard.service`。確認應用程式 startup 完成及 listener 可連線；不要只看瞬間 active 就說網站可用。需 API 驗證時在本機讀取密碼於程序記憶體中，不輸出值，也不建立包含 cookie 的 tracked 檔案。

Monitor 部署由 `~/host-device-monitor/scripts/install-collector.sh` 管理；sudo 安裝需要管理員認證時，完成本機程式及檢查後提供可審查的命令，請使用者在主機端執行，禁止索取聊天密碼或繞過權限。已獲授權的部署不再重複詢問批准。

驗證 monitor 時記錄 ActiveState、SubState、PID、NRestarts，隔一小段時間重新讀取，確認計數未增加；只分析此次啟動時間之後的 journal，避免舊錯誤混入。systemctl --failed 為零不能排除 auto-restart 迴圈。維持原有監控範圍限制，回報未實際驗證的接拔／電源事件。

## GitHub 與交接

公開分享 repository 為 service-harbor，不含舊主機 Git 歷史；私人維運 repository 另行保留。使用 gh 處理 GitHub、SSH git push。只提交程式、通用範例及文件，禁止 data/、local-catalog、環境檔、密碼、session、SSH key。公開 snapshot 必須排除歷史規劃 docs/superpowers，並檢查 archive 檔案清單。不得將私人 .git 搬入公開版或直接推送私人分支至公開 remote。

修改後同步相關 docs。交接說明：改了什麼、如何驗證、是否已安裝到執行主機、是否已推到 GitHub、尚未完成或驗證的項目。不能以來源檔修好來宣稱已安裝單元正在執行修正版。

## 安裝生命週期

setup.sh（venv／pip）／setup-uv.sh（uv venv／uv pip）／reset.sh／uninstall.sh 呼叫 scripts/lifecycle.py，以一般使用者執行，禁止 root pip／整支 sudo。systemd 範本須替換參數後使用，不直接 install。兩種模式皆設定 linger；system 模式以 User= 一般帳號執行並給程序 systemd-journal 讀取權，不新增 sudoers 或帳號群組。重置保留業務資料、撤銷 session；移除清除私密資料及 venv、保留原始碼和既有 sudoers／linger。除非使用者要求實際重裝／移除，不在正式主機執行生命週期腳本；可做語法與生成單元的唯讀檢查。

uv 安裝模式使用目前 Python 並禁止自動下載 Python，不要求環境有 pip／ensurepip。兩個 setup 入口共用 .venv，沿用既有環境不清除。install.json 保存 backend，reset 預設沿用；不要讓 uv 模式誤走 pip 前置檢查。

## 分享修正維護規則

預設 catalog 只保留 Dashboard。其他主機固定清單存 gitignored local-catalog.json；不可再硬編碼個人 unit。所有 JSON 讀改寫必須經 storage 共用鎖；多檔更動用 transaction，不得旁路 direct write。session 不快取，SSE 靜默時仍需定期驗證。密碼規格改共用 password-policy.json。匯入必須逐塊限制位元組，不回退為 request.body()。驗收以 TASKS.md 與 tests/ 為準，測試必須隔離 DATA_DIR。
