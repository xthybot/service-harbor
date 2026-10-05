# 安全與一致性修正驗收

日期：2026-10-04。此紀錄區分原始碼、隔離模擬與真實環境；以本次提交的檔案及測試輸出為準。

實作提交：`3e2a211`。已快轉合併至本機 `main`；沒有推送 GitHub，也沒有部署正式服務。

| 問題 | 原始碼修正 | 隔離測試證據 |
| --- | --- | --- |
| 登出失敗卻顯示成功；舊登入回應污染新世代 | `async-state.js` 以 auth epoch 及 AbortController 管理請求；`app.js` 統一清理視窗、待確認、inventory、Live、Tracking、SSE，登出期間鎖住登入並以 epoch 拒絕舊回應，失敗顯示 Retry sign out。後端撤銷 token 不發刪除 cookie 回應 | `frontend-async.test.cjs`：403 登出、登出期間登入、舊 401／晚回 body、modal 清理、重試與 SSE session 去重退避；`test_consistency.py` 檢查登出回應不刪後來的 cookie |
| JSON 預覽後可無條件覆蓋或發生變動 | `config_transfer.py` 對文件及設定快照簽發限時憑據，交易內確認；409 要求重新預覽。前端無衝突送 overwrite=false，衝突全部列出 | `test_consistency.py` 預覽後新增衝突、修改 URL、改文件、skip/overwrite；`test_release.py` HTTP 409／重新預覽；Node 實際匯入視窗 mock |
| 慢 SSH／systemd probe 阻塞共用 JSON 鎖 | `main.py` 先取快照，鎖外唯讀 probe，短交易內重核主機與服務版本；`registry.py` 再檢重複單元與信任 | `test_consistency.py` 控制 probe 延遲，期間完成登入、登出、一般讀取及主機異動，最後拒絕過時結果 |
| External URL 可被相容 API 清空；URL authority 驗證不足 | `registry.py` 共用新增／編輯／匯入欄位規則；`service_urls.py` 及 `service_ports.py` 阻止無效覆寫；`service_url_validation.py` 驗證 host、IDNA／IPv6 與字元。既有無效資料拒絕匯出，但仍允許直接編輯修復 | `test_consistency.py` settings 失敗後 export/import round-trip、既有無效 URL 修復、惡意 authority 與合法 localhost/IP/IDNA |
| 卸載失敗不能重試或會刪混用資料 | `lifecycle.py` 記錄原 DATA_DIR 與 ownership；ENV/receipt 一致性、路徑保護、已知 JSON／SSH pin 清單、未知保留、各階段重試 | `test_lifecycle.py`：刪檔失敗重跑、ENV 不一致、`..`、symlink、假 JSON 目錄、混用 ssh、未知暫存檔及 legacy adopt |
| session 撤銷可能被舊交易還原；安裝失敗回復互相阻斷 | `revoke-sessions` 先 recovery 後共用交易清空；rollback 各階段獨立記錄，資料不一致時不重啟舊服務 | `test_lifecycle.py`：舊 journal 復原／損壞、不同 rollback 故障、原 session 不恢復，uv／venv 分支與 unit 編碼 |
| Status/Recent 晚回覆、SSE 重播或仍追蹤舊 unit | `app.js` drawer/log generation 與 desiredFollow；服務清單回傳包括遠端地址／信任的執行身分，變動時重建暫停中的 drawer；`systemd.py` journal cursor、identity、gap 事件；`main.py` 續傳與身分參數 | `frontend-async.test.cjs`：A→B／同 ID 重開／Pause 競態／同 host ID 改地址身分／相同文字保留；`test_journal.py`：清單身分、cursor、remote 命令、缺口、host 變動、靜默撤銷與子程序終止 |
| 其他前端狀態與視窗問題 | Favorite 依 ID 更新新 inventory、busy 依目前服務重算、Hosts load 排隊刷新、Open ports 空結果、modal 頂層 Escape／焦點 | Node mock 驗證 Favorite、busy、空 Port、modal Ctrl+K/Escape/focus；其他項目對照事件及刷新程式路徑 |
| 文件中的 sudoers、Monitor、備份與安裝路徑易誤導 | 預設註解 sudoers、visudo 先檢驗、分開同機還原／跨機遷移與 Monitor 額外安裝；記載已驗證 Ubuntu/Python 範圍 | 文件與程式路徑審查；`visudo -cf`、Python/JS/shell 語法及 `git diff --check` 最終再驗證 |

## 已完成的隔離檢查

- Python：`/home/xthybot/host-service-dashboard/.venv/bin/python -m unittest discover -s tests -q`，88 項通過；使用本機已存在的依賴作測試 runtime，資料使用 TemporaryDirectory，未修改該私人專案。
- Node：`node --test tests/*.test.cjs`，16 項通過；實際 UI 程式由 VM 搭配可控 fetch／EventSource／DOM 執行。
- Python `compileall`、各 JS `node --check`、shell `bash -n`、`visudo -cf sudoers/host-service-dashboard`、`git diff --check` 均通過。
- lifecycle 特權命令在測試中 fail-closed mock。早期建立回歸測試時，曾有一次模擬 rollback 間接嘗試 `sudo -v`，因無 TTY／認證遭系統拒絕；沒有執行 systemctl 操作或改動系統。測試已改成預設拒絕任何未 mock 子程序。

## 真實環境與未驗證項目

- 唯讀確認這台測試主機為 Ubuntu 24.04.3 LTS、Python 3.12.3。未在正式主機執行重新安裝、reset、uninstall、systemd 啟停、SSH 控制或實體重新開機。
- 未動態驗證其他 Ubuntu／Python 版本、真實 SSH journal cursor 或 journal vacuum 的系統行為；mock 驗證的是命令建構、缺口顯示與串流清理。正式部署前應在一次性 Ubuntu 環境跑安裝／遷移／移除，再按相同版本於測試主機核對日誌續傳。
- 尚未部署執行中的 Dashboard，也未推送 GitHub。更新正式服務需要另行授權；部署前需私密備份資料、確認 DATA_DIR ownership、核對實際 unit 與 user manager UnitPath。若既有部署缺 ownership 標記，依安裝文件執行離線 `adopt-data`。

## 2026-10-05：卸載 pin 清理的失敗重試修正

根因：原先 `cleanup_data()` 以 `hosts.json` 計算 pin 清單，卻先刪除 `hosts.json`，再刪除 `ssh/*.known_hosts`。若 pin 刪除失敗，重跑時清單變空，造成已登記 pin 殘留。

修正：刪除資料前先把經驗證的 pin 檔名寫入專用清理紀錄，摘要存入安裝收據。重試核對歸屬、路徑、檔案類型、摘要與檔名；紀錄損壞、竄改、symlink 或不合法檔名均停止。成功後才清除紀錄。未知 pin 與混用 `ssh/` 內容保留。

隔離驗收：`tests/test_lifecycle.py` 使用 `TemporaryDirectory`、虛構主機資料及模擬 systemctl；注入已刪 `hosts.json` 後的 pin 刪除錯誤，重跑確認只刪登記 pin；另檢查損壞與遭竄改紀錄、路徑穿越、symlink、紀錄建立失敗，以及資料清完但紀錄刪除失敗後再次重試。`/home/xthybot/host-service-dashboard/.venv/bin/python -m unittest discover -s tests -q` 共 93 項通過；`python -m py_compile scripts/lifecycle.py tests/test_lifecycle.py` 與 `git diff --check` 通過。此次沒有讀取正式 SSH key、正式資料，也沒有執行正式 sudo 或服務啟停。

未實機驗證：真實 Ubuntu 卸載、權限故障恢復、突然斷電後的持久性，以及舊版已遺失 `hosts.json` 且沒有清理紀錄的殘留 pin 辨識。舊版殘留需人工核對，不能按檔名通配刪除。此次未部署、未推送 GitHub。

## 2026-10-06：SSH 主機與 pin 操作一致性修正

根因：`delete_host()` 原本先從 `hosts.json` 移除主機再刪 pin，失敗後無主機 ID 可重試或供 uninstall 辨識；`save_host()` 修改位址／Port 時先刪 pin 再寫 JSON，寫入失敗可能留下 trusted 主機但缺少 pin。重新信任已有主機時也可能先替換 pin，卻因 JSON 寫入失敗而保留舊的 trusted 資料。

修正：單一 `hosts.json` 原子寫入先保存未信任與 `pin_cleanup_pending` 狀態，再刪精確主機 ID 的 pin，最後寫入完成狀態或移除主機。失敗／程序中斷後可依磁碟上的同一主機資料重試；清理未完成時拒絕 SSH 與重新信任。重新信任時先撤銷舊 trusted 狀態，再替換 pin。Host 頁面遇到操作錯誤會重新載入狀態；uninstall 的 pin 清單仍可從待刪主機 ID 建立。沒有通配刪除其他 pin 或金鑰。

隔離驗收：`tests/test_ssh_host_consistency.py` 使用 `TemporaryDirectory`、虛構主機／pin，注入刪 pin 錯誤、位址與 Port 首次 JSON 寫入錯誤、最後寫入錯誤、重新信任錯誤及獨立子程序中斷；重試後只清理指定 pin，未知 pin、其他主機 pin 與私鑰保持不變。`tests/test_lifecycle.py` 確認卸載清單包含待刪主機的 pin，並保留未知 pin。`tests/frontend-async.test.cjs` 驗證刪除與重新信任失敗後 Host 卡片重新載入未信任狀態，待刪狀態顯示 Removal pending。未讀取正式資料或金鑰，未執行正式 SSH、sudo 或服務控制。

最終檢查：

- `/home/xthybot/host-service-dashboard/.venv/bin/python -m unittest discover -s tests -q`：100 項通過；僅借用既有測試 runtime，沒有修改私人專案。
- `node --test tests/*.test.cjs`：18 項通過。
- `python3 -m py_compile app/ssh_hosts.py tests/test_ssh_host_consistency.py tests/test_lifecycle.py`、`node --check app/static/hosts.js` 及 `git diff --check` 均通過。

未實機驗證：正式 Dashboard 的主機編輯／刪除、真實檔案權限故障與突然斷電後的使用者操作。更新執行中的後端需另行部署及重啟；此次未部署或推送。
