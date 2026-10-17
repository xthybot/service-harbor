# Service Harbor

供可信任區域網路使用的 Linux 服務管理網站。Dashboard 以一般使用者執行，提供本機與 SSH 遠端主機的 systemd 狀態、控制和 journal；也能記錄與檢查手動指定的 TCP Port。介面採原生 HTML／CSS／JavaScript，後端為 FastAPI，不需要資料庫或前端建置流程。

目前部署網址：`http://<Dashboard 主機的區網 IP>:8765/`。安裝時可選 user／system 模式、監聽位址和 Port（預設 `0.0.0.0:8765`）。獨立的裝置監控網站是可選專案，若另行安裝，預設可位於 `http://<相同 IP>:8766/`；其原始碼與安裝流程不隨本 repository 提供。

## 使用範圍與傳輸安全

**本服務僅適合可信任的私人區域網路，不適合直接放在公開網際網路、公共 Wi-Fi 或不受信任的共享網路。** 預設 HTTP 不提供傳輸加密，登入密碼、session cookie 與服務／Log 資料可能被沿途讀取或竄改；設定登入密碼不等於使用 HTTPS。不要直接設定公網 Port forwarding。需要跨網路存取時，應另外部署受控 VPN，或正確設定 HTTPS 反向代理與存取限制；此安裝器不自動提供 TLS。

## 乾淨預設與可選範例

新安裝預設只有 Dashboard 自身，沒有任何原作者的主機服務清單。其他服務從 Add service 建立，或將 `examples/services.json` 內的虛構 unit／Port 改成自己的設定後匯入；匯入不會安裝或啟動系統服務。

既有部署的本機清單可放在私密 `data/local-catalog.json`，與其他設定同樣不納入 Git；它不是公開版必需檔案。不要將私密匯出 JSON 或 local-catalog.json 放進分享 repository。

## 頁面與日常操作

| 頁面 | 功能 |
| --- | --- |
| Overview | 跨服務／主機／Port 搜尋、Needs attention 異常清單、最愛捷徑、主機與 TCP Port 摘要，以及限時追蹤倒數。 |
| Services | Total／Running／Stopped／Failed 摘要、主機／狀態／分類及 User／System／Favorites 篩選、服務詳情、啟停控制、Status 與 journal。 |
| Open ports | 顯示已設定 Port 的 TCP 連通結果、檢查時間和所屬主機；管理手動 Port 紀錄。 |
| Hosts | 註冊 SSH 主機、取得 Dashboard 公鑰、核對主機指紋、檢查連線。 |
| Add service | 註冊本機／遠端現有 unit 或外部網站連結，並匯入服務設定 JSON。 |

Services 卡片可直接開啟詳情。已設定 systemd unit 的服務提供 systemd 狀態、控制與 journal；所有服務均可另外啟用下述連通檢查；User scope 使用該帳號的 user manager，System scope 的控制需要針對確切 unit 與動作授權。啟停／重啟前有確認視窗，結果以提示訊息顯示。Log 支援最近紀錄、SSE 即時追蹤、關鍵字與嚴重程度篩選，以及複製最近 5／10／20 行。頂端 **Not live／Live** 控制服務狀態與 Port 的選取輪詢；即使是 Not live，開啟服務詳情後的 Log 仍會即時追蹤，可用 Log 的 **Pause** 暫停。

### 服務連通檢查

新增或編輯任何服務（包含已有 systemd unit 的服務）時，可設定 **Check method**：

- **Disabled**：僅提供 Open；既有服務預設維持此行為，不會因更新而自動發出網路請求。
- **HTTP / HTTPS**：從 Dashboard 主機對 Open URL 發出 GET，只讀回應標頭；2xx／3xx／401／403 顯示 Running，其他回應、連線失敗、憑證錯誤或逾時顯示 Stopped。不自動跟隨轉址，不傳登入 cookie，也不略過 HTTPS 憑證驗證。
- **TCP**：嘗試連線至自訂 TCP host／port；留空的欄位取自 Open URL（HTTP 預設 80、HTTPS 預設 443）。連通顯示 Running，失敗顯示 Stopped；不代表網頁功能正常。

Services 卡片及詳情顯示 systemd 與連通檢查各自的時間；詳情 Status 顯示方法、目標、HTTP 狀態碼或失敗原因。檢查沿用單次更新、Live 三秒與鈴鐺五秒追蹤，沒有後端常駐排程。有 unit 的服務仍以 systemd 判斷 Running／Stopped／Failed，另列 HTTP／TCP 連通結果與檢查時間；沒有 unit 的服務不提供 Start／Stop／Restart 或 journal。Services 的 Service port 只記錄 Port，不會額外自動探測該 Port；只執行設定的 Check method。Open ports／Overview 的 TCP inventory 仍可獨立檢查記錄的 Port。設定隨 JSON 匯出／匯入；舊 JSON 缺少欄位時視為 Disabled。實測範圍及重跑方式見 [純網頁檢查驗收](docs/WEBSITE_CHECK_ACCEPTANCE.zh-TW.md)。

Open ports 對已記錄的目標從 **Dashboard 主機** 嘗試 TCP 連線；Open 只代表該位址與 Port 可連通，不代表 HTTP 健康或 systemd unit 正常。手動 Port 可在此新增、修改與刪除。來自 Services 的 Port 在此只顯示唯讀詳情，右上角 **View service** 會開啟對應的服務詳情；修改或移除其 Port 請到 Services。Port 數字由設定提供，系統不使用 `ss` 掃描主機或執行遠端 Port 查詢。

服務可設定顯示名稱、分類、描述、最愛和 Open URL。Open URL 可指向公開網域，與監測用 Port 分開；Open 會在使用者瀏覽器的新分頁開啟。Services 可匯出全部、單一類別、最愛、手動新增或單一服務的設定 JSON；Add service 可預覽並匯入，遇到重複項目時選擇覆蓋或跳過。匯入／匯出不會帶入 SSH 私鑰、密碼或指紋。

預設沒有每三分鐘全站輪詢。初次登入、進入 Open ports、手動刷新或篩選會進行單次資料更新；選取服務或 Port 會檢查該項，切換為 Live 後每三秒只輪詢目前選取項目。登入 session 有效七天，Dashboard 重啟後仍保留；SSE 每五秒檢查是否過期或撤銷，失效時終止 journal／SSH 串流程序。

## 安裝入口

在 Ubuntu 以一般使用者執行（不要加 sudo）：

```bash
git clone https://github.com/xthybot/service-harbor.git "$HOME/host-service-dashboard"
cd "$HOME/host-service-dashboard"
bash scripts/setup.sh       # Python venv／pip 版本
# 或選擇 uv 版本（先自行安裝 uv）
# bash scripts/setup-uv.sh
```

安裝器會詢問**密碼、監聽 IP（預設 0.0.0.0）、Port（預設 8765）及 user／system 模式**，逐步顯示進度，安裝完成便啟動並確認 HTTP 可用，再提供 LAN 網址。兩種模式都由一般帳號執行網站，僅必要的系統設定要求 sudo；不建立免密碼 sudoers。user 模式會設定 linger，確保尚未登入也能開機啟動。

公開分享 repository 為 `service-harbor`；亦可使用 HTTPS clone，無需私人 repository 存取權。缺少 Python／venv／pip 時會提示 `sudo apt update` 與 `sudo apt install python3 python3-pip python3-venv`，不自動安裝 apt 套件；詳細需求、權限、模式切換及防火牆請見 [安裝說明](docs/INSTALLATION.zh-TW.md)。

uv 版本使用 `uv venv` 與 `uv pip`，不需要 python3-pip／python3-venv，但仍需要 Python 3 執行安裝器。兩個入口共用安裝流程，重置會沿用上次成功安裝的工具；詳見 [兩種安裝方式](docs/INSTALLATION.zh-TW.md)。

### 連通異常提示

Services 新增 **Connectivity issues** 黃色摘要，可點擊篩出啟用檢查且連通失敗的服務；這是獨立統計，可能同時包含 Running、Stopped、Failed 的項目。主燈優先順序為 systemd Failed 紅色、Running 但連通失敗黃色、Stopped 灰色；Stopped／Failed 仍另外顯示黃色連通異常 badge。無 unit 的服務連通失敗則顯示黃燈。未啟用檢查不會因記錄 Port 而列入此分類。

Overview 的 Needs attention 會列出服務連通異常。有對應 Service 的異常會開啟 Services 的該服務詳情並清除列表篩選；只有獨立 Port 才導向 Open ports。相同服務的連通異常與重複 Port 提示會合併。Port 以 service_id 或可唯一辨識的相同主機與 Port 關聯，不以顯示名稱猜測。

### 既有安裝更新

已安裝者請在原目錄更新，**不要重新 clone 覆蓋原目錄，也不要執行 reset／uninstall**。此次功能不變更依賴或 systemd 設定；只需更新程式並重啟 Dashboard。`data/`、密碼、Hosts 和 SSH key 維持原位，操作步驟及有本地修改時的處理方式見 [維運更新說明](docs/OPERATIONS.zh-TW.md#更新與推送)。

### 重置與移除

```bash
# 重設密碼／監聽位址／Port，重建 systemd，保留服務、Hosts、SSH key
bash scripts/reset.sh

# 停用並移除 systemd、密碼、資料、SSH key 和 .venv；保留原始碼
bash scripts/uninstall.sh
```

兩個腳本均會顯示處理步驟並要求確認；移除須輸入 `REMOVE`。重置會撤銷舊登入 session。模式由既有單元／安裝紀錄辨識，不會刪除其他被 Dashboard 管理的服務；既有 sudoers 與 linger 不自動移除。詳見 [重置與移除範圍](docs/INSTALLATION.zh-TW.md) 和 [設定檔說明](docs/CONFIGURATION.zh-TW.md)。

## 文件導覽

| 文件 | 適合查找的內容 |
| --- | --- |
| [安裝與啟動](docs/INSTALLATION.zh-TW.md) | 首次部署、開機常駐、LAN 連線、精確 sudoers 與移除。 |
| [設定參考](docs/CONFIGURATION.zh-TW.md) | 環境變數、資料檔、服務與 Port 設定、JSON 匯入／匯出。 |
| [維運與備份還原](docs/OPERATIONS.zh-TW.md) | 更新、密碼與 session、私密資料備份、故障排查。 |
| [架構與 API](docs/ARCHITECTURE.zh-TW.md) | 模組、資料流程、API、刷新與權限界線。 |
| [SSH 主機管理](docs/SSH_HOSTS.zh-TW.md) | 公鑰、主機指紋、遠端命令、journal 與控制權限。 |
| [裝置監控整合](docs/DEVICE_MONITOR.zh-TW.md) | 獨立監控網站與 Dashboard 的關係。 |
| [本次安全修正驗收](docs/SAFETY_REMEDIATION_ACCEPTANCE.zh-TW.md) | 登入、匯入、日誌與安裝生命週期的隔離測試及未驗證範圍。 |
| [AGENTS.md](AGENTS.md) | 開發與維運代理的工作規則和交接清單。 |

公開版不包含私人版本的 `docs/superpowers/` 歷史規劃；現行操作以程式、systemd 範本與上表文件為準。

## 權限與資料

Dashboard 不以 root 執行。User scope 控制不使用 sudo；System scope 控制限於 allowlist 與主機上明確列出的 `sudo -n systemctl` 規則。Journal 讀取權限另行配置。遠端 SSH 使用 Dashboard 專用金鑰、已核對的 host key 與非互動命令；沒有提供任意 shell API。

GitHub 分享 repository 只保存程式、通用範例與文件。實際密碼、session、服務別名與網址、主機設定、SSH 私鑰、journal 及 `data/` 不在 Git 中，須另做私密備份。此 HTTP 網站應只供可信任區網使用，請勿直接對網際網路開放。

限時追蹤：Services／Open ports 個別項目的藍色鈴鐺可選 5／10／20 分鐘或 1 小時，每 5 秒更新；Overview 顯示倒數。關閉網頁停止查詢，重新開啟會依原到期時間恢復。詳見 [設定指南](docs/CONFIGURATION.zh-TW.md)。

## 驗收

原分享修正及本次安全修正的 task 與可重跑驗收見 [TASKS.md](TASKS.md)、[分享版驗收紀錄](docs/RELEASE_ACCEPTANCE.zh-TW.md) 與 [安全修正驗收紀錄](docs/SAFETY_REMEDIATION_ACCEPTANCE.zh-TW.md)。測試只使用臨時資料與模擬日誌程序，不需控制正式服務。

## 授權

本專案可由著作權人授權的原創程式碼與文件採用 [MIT License](LICENSE)，署名為 `Copyright (c) 2026 xthywork`。第三方套件與素材仍依各自授權條款，不因本專案的 MIT 授權而變更；授權盤點與保留的原始聲明見 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
