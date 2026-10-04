# Service Harbor

供可信任區域網路使用的 Linux 服務管理網站。Dashboard 以一般使用者執行，提供本機與 SSH 遠端主機的 systemd 狀態、控制和 journal；也能記錄與檢查手動指定的 TCP Port。介面採原生 HTML／CSS／JavaScript，後端為 FastAPI，不需要資料庫或前端建置流程。

目前部署網址：`http://<Dashboard 主機的區網 IP>:8765/`。安裝時可選 user／system 模式、監聽位址和 Port（預設 `0.0.0.0:8765`）。獨立的裝置監控網站位於 `http://<相同 IP>:8766/`，其原始碼與安裝流程在 `~/host-device-monitor`。

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

Services 卡片可直接開啟詳情。只有已設定 systemd unit 的服務才有狀態、控制與 journal；User scope 使用該帳號的 user manager，System scope 的控制需要針對確切 unit 與動作授權。啟停／重啟前有確認視窗，結果以提示訊息顯示。Log 支援最近紀錄、SSE 即時追蹤、關鍵字與嚴重程度篩選，以及複製最近 5／10／20 行。頂端 **Not live／Live** 控制服務狀態與 Port 的選取輪詢；即使是 Not live，開啟服務詳情後的 Log 仍會即時追蹤，可用 Log 的 **Pause** 暫停。

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
| [AGENTS.md](AGENTS.md) | 開發與維運代理的工作規則和交接清單。 |

`docs/superpowers/` 內的規格與計畫是建立時的歷史紀錄，保留原貌供追溯；現行操作以程式、systemd 範本與上表文件為準。

## 權限與資料

Dashboard 不以 root 執行。User scope 控制不使用 sudo；System scope 控制限於 allowlist 與主機上明確列出的 `sudo -n systemctl` 規則。Journal 讀取權限另行配置。遠端 SSH 使用 Dashboard 專用金鑰、已核對的 host key 與非互動命令；沒有提供任意 shell API。

GitHub 分享 repository 只保存程式、通用範例與文件。實際密碼、session、服務別名與網址、主機設定、SSH 私鑰、journal 及 `data/` 不在 Git 中，須另做私密備份。此 HTTP 網站應只供可信任區網使用，請勿直接對網際網路開放。

限時追蹤：Services／Open ports 個別項目的藍色鈴鐺可選 5／10／20 分鐘或 1 小時，每 5 秒更新；Overview 顯示倒數。關閉網頁停止查詢，重新開啟會依原到期時間恢復。詳見 [設定指南](docs/CONFIGURATION.zh-TW.md)。

## 驗收

六項分享修正的 task 與可重跑驗收見 [TASKS.md](TASKS.md) 和 [驗收紀錄](docs/RELEASE_ACCEPTANCE.zh-TW.md)。測試只使用臨時資料與模擬日誌程序，不需控制正式服務。

## 授權

本專案可由著作權人授權的原創程式碼與文件採用 [MIT License](LICENSE)，署名為 `Copyright (c) 2026 xthywork`。第三方套件與素材仍依各自授權條款，不因本專案的 MIT 授權而變更；授權盤點與保留的原始聲明見 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
