# 架構與 API

## 程序與權限

瀏覽器透過同源 HTTP 使用 Dashboard，FastAPI 以一般帳號執行。設定資料保存在本機私密 JSON；systemctl、journalctl 與 SSH 指令使用固定 argument list 和 subprocess，沒有任意 shell API。Port 檢查使用 Python TCP 連線，不呼叫 `ss`，也不登入遠端主機掃描 Port。

user 單元控制使用 systemctl --user；system 單元先檢查 catalog，再用 `sudo -n /usr/bin/systemctl <action> <unit>`。sudoers 逐項列出動作與 unit。監控收集器與檢視器原始碼位於獨立的 `~/host-device-monitor` 專案；Dashboard 仍可透過通用服務 API 顯示並控制其 systemd 單元。

## 原始碼索引

| 路徑 | 職責 |
| --- | --- |
| app/main.py | FastAPI 路由、驗證入口、靜態頁面與 SSE |
| app/storage.py | 所有 JSON 共用 thread/process lock、atomic write、可回復多檔交易 |
| app/password_policy.py、static/password-policy.json | 安裝/API/瀏覽器共用密碼規則 |
| app/security.py | 密碼比對、session 雜湊與持久化、同源檢查、登入限速 |
| app/catalog.py | 內建與已註冊服務的動態 allowlist |
| app/registry.py | 私密主機與服務 JSON、註冊／移除及驗證 |
| app/ssh_hosts.py | 專用金鑰、公鑰 API、指紋 pin、SSH 固定指令 |
| app/service_url_validation.py | 無儲存依賴的共用 URL 驗證 |
| app/static/hosts.js | 主機設定、公鑰、fingerprint modal 與連線檢查 |
| app/systemd.py | 本機／遠端單元狀態、允許的控制與 journal subprocess |
| app/service_ports.py | 服務 Port 覆寫；內建 catalog Port 可由空值覆寫移除 |
| app/service_names.py | 服務顯示別名 |
| app/service_urls.py | Open URL 覆寫 |
| app/service_favorites.py | 最愛設定 |
| app/manual_ports.py | 手動 Port 紀錄、服務 Port 清單、重複檢查與 TCP 連通檢查 |
| app/config_transfer.py | 服務設定 JSON 匯出、預覽及匯入 |
| app/static/index.html | 頁面結構、modal、drawer |
| app/static/app.js | 頁面切換、API、刷新與服務日誌 SSE |
| app/static/overview.js、overview.css | 首頁搜尋、異常分類、最愛清單與主機／TCP 摘要；以 inventory／hosts 事件接收既有資料，不新增背景輪詢 |
| app/static/add-service.js | 註冊既有 unit／外部連結、主機選擇與表單預覽 |
| app/static/manual-ports.js | 手動 Port 的檢查、新增、編輯與刪除視窗 |
| app/static/config-transfer.js | 服務設定 JSON 匯出、匯入與重複項目預覽 |
| app/static/styles.css | Responsive 視覺樣式 |
| systemd/ | 由安裝器替換參數的 Dashboard user／system 單元範本 |
| scripts/setup.sh、reset.sh、uninstall.sh、lifecycle.py | 一般帳號互動安裝／重建／移除，必要步驟才 sudo；不生成 sudoers |
| sudoers/host-service-dashboard | 預設全註解的精確命令範本；不授權真實單元 |
| scripts/ | Dashboard setup |

## API

除 session 探測與登入外，資料 API 都需要 session。寫入 API 同時驗證 Origin。靜態 shell 與資源可以載入，實際主機資料需登入。

| Method / Path | 行為 |
| --- | --- |
| GET /api/session | 登入與密碼是否設定 |
| POST /api/login | password 欄位，成功建立 cookie |
| POST /api/logout | 撤銷目前 session |
| GET /api/services | catalog 單元狀態、啟動時間、設定的 Port、別名、最愛、自訂 URL |
| PUT /api/services/{id}/settings | 相容路由：display_name、open_url 與選填的 port |
| PUT /api/services/{id}/edit | Services 詳情的完整設定；手動新增服務可改 Host／scope／unit，內建服務的這三項固定 |
| PUT /api/services/{id}/display-name | display_name，相容的單獨別名設定 |
| PUT /api/services/{id}/favorite | favorite 布林值 |
| GET/POST /api/ssh-key | 讀公鑰／建立專用 key，絕不回傳私鑰 |
| GET/POST /api/hosts | 主機清單／新增 |
| PUT/DELETE /api/hosts/{id} | 編輯／刪除（服務引用時拒絕） |
| POST /api/hosts/{id}/scan | 掃描並保存待核對 fingerprint |
| POST /api/hosts/{id}/trust | 比對並確認待核對 fingerprint |
| POST /api/hosts/{id}/check | SSH、systemd 與 system journal 檢查 |
| POST /api/services | 正式註冊本機／遠端單元或外部 URL |
| GET /api/services/export | selection=all／favorites／registered／category／service；匯出不含金鑰、密碼及主機顯示名稱的 JSON |
| POST /api/services/import/preview | 驗證並預覽，回傳綁定資料版本及匯入內容的短期 preview_token |
| POST /api/services/import | overwrite 預設 false；覆蓋需在 X-Import-Preview 帶確認憑據，版本衝突回 409；主機以未信任狀態新增 |
| DELETE /api/services/{id} | 只移除自訂 Dashboard 註冊，不改 unit |
| GET /api/ports | 對服務已設定的 TCP Port 連線檢查，回傳 Open／Unreachable 與檢查時間 |
| GET /api/ports/check | 依已儲存的服務或手動 Port ID，只檢查指定 Port |
| DELETE /api/ports/service/{id} | 從 Services 編輯視窗取消服務 Port，不刪除服務或 unit |
| GET /api/services/{id}/live | 只讀指定 unit 的狀態，有設定 Port 時也做 TCP 檢查 |
| GET/POST /api/ports/manual | 手動 Port 紀錄的 TCP 檢查結果／新增紀錄 |
| POST /api/ports/manual/check | 儲存前的 TCP 檢查與同主機同 Port 提示 |
| PUT/DELETE /api/ports/manual/{id} | 修改／移除手動 Port 紀錄 |
| POST /api/services/{id}/actions/{action} | start／stop／restart；回傳 ok 與 message |
| GET /api/services/{id}/status | systemctl status 文字 |
| GET /api/services/{id}/logs | lines（預設 200，上限 1000）、query 搜尋；回傳 lines、journal cursor 與執行身分 |
| GET /api/services/{id}/logs/stream | SSE；cursor／Last-Event-ID 接續及 identity 保護，無續傳點時明示缺口 |

SSE `message` 以 `id: <journal cursor>` 及 JSON `data: {"line": "..."}` 傳送；續傳以 cursor 而非文字去重。同一文字的不同 journal 事件各自保留。`gap` 表示無法證實連續性；`identity_changed` 會關閉舊串流並要求重載。連線結束時清理 journalctl／SSH subprocess。服務 card 控制前使用 modal，API 回傳失敗時以錯誤 toast 呈現。

Open ports 的服務來源列在瀏覽器中只顯示唯讀視窗，可直接前往對應的 Services 詳情；沒有專供 Open ports 修改服務 Port 的 PUT API。手動 Port 由 `/api/ports/manual` 管理。服務 Port 的修改仍可透過 Services 的完整編輯 API；取消設定也只能由 Services 介面觸發。

## Device Monitor

獨立專案 `~/host-device-monitor` 提供收集器、Port 8766 的唯讀檢視器與其安裝文件。Dashboard 預設不含 `host-device-monitor.service` 卡片；另外安裝並在 Add service 註冊後，才使用通用服務狀態、控制與日誌 API；舊 `/#monitor` 書籤會導向獨立網站。

## 已知界線

catalog 合併 Dashboard 自身、私密 local-catalog 與已持久化的服務註冊，每次讀取都反映新增／移除。Open ports 以 Dashboard 主機對已記錄的位址與 Port 做 TCP 連線；Open 不能證明連到的是原本設定的 unit，也不能證明 HTTP 健康。one-shot inactive 服務會映射為 Stopped；systemctl 正在 activating／deactivating 等狀態也會映射為 Stopped，需開 status 或檢查 journal 判斷細節。setup／reset 更換密碼會撤銷 session；僅手動編輯環境檔不自動撤銷，需依維運指引處理。

沒有固定週期的全站刷新。頂端即時切換啟用時，只對目前選取的服務或 Port 每 3 秒查詢一次；切換選取或離開頁面會停止。Log 的 SSE 連線獨立於頂端即時切換，開啟有 unit 的服務詳情後仍會開始追蹤，使用 Log 的 Pause／Resume 控制。前端程式更新後，使用者需載入新版 HTML／JS。首頁與 static 資源回傳 Cache-Control: no-store，index.html 也保留資源版本 query。

## 主機與新增服務

`#hosts` 先保存 SSH 主機，專用 Ed25519 私鑰只保存在 data/ssh。掃描的 host fingerprint 需使用者獨立核對、手動確認後才寫入 per-host known_hosts。每次 SSH 用嚴格 pin 與固定單次指令，無互動 shell。狀態、journal 與控制按 service host/type 分派；各服務 Port 依其所屬 Host 顯示。TCP 檢查從 Dashboard 主機連線，不執行 socket 掃描或遠端 Port 指令。

`#add-service` 的 Host 欄提供 This host、已註冊的遠端 SSH 主機及 External website；前端由選項決定 Local／Remote SSH／External URL 類型，既有 API 欄位不變。Local／Remote 有填 unit 時，唯讀確認單元存在後才持久化；Remote 有 unit 時必須指向已註冊且信任的主機。External URL 無單元欄位，也無 journal／控制。新增／編輯的唯讀 unit 檢查在全域 JSON 鎖外執行；儲存前在短交易中重新核對主機信任、執行身分及重複條件，異動時回 409。新服務 ID 使用 svc-UUID，避免不同主機的同名 unit 衝突；原本單元 ID 保持不變。

Services 的 JSON 匯出／匯入使用 `app/config_transfer.py`。輸出是可攜帶的服務設定，不含 SSH 信任資料與秘密；匯入以遠端位址及 SSH 使用者對應主機，先驗證完整文件後再寫入現有 JSON 設定檔。新增主機保持未信任，匯入不執行 SSH、systemctl 或 journalctl。一般 Add service 路徑仍維持原本的即時 unit 檢查。

舊 `#links` 書籤導向 Add service，書籤 API 與頁面已移除。URL 在 Services 詳情的設定視窗修改。Add service 不保存 localStorage 草稿，也沒有清空或草稿匯出按鈕；正式匯出由 Services 頁的 Export JSON 提供。完整設置與限制見 [SSH 主機管理](SSH_HOSTS.zh-TW.md)。

`app/static/tracking.js` 管理使用者啟動的限時五秒查詢與瀏覽器到期時間；透過 app.js 的 trackingCheck 更新既有 inventory 及目前 Log 視窗，不新增後端排程或 API。
