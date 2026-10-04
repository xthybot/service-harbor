# 安裝、重置與移除

## 前置需求

Ubuntu Server、systemd、Python 3（目前隔離測試於 Ubuntu 24.04.3 LTS／Python 3.12.3 執行；其他 Ubuntu／Python 組合尚未完整驗證）、OpenSSH client，以及所選安裝入口需要的 venv／pip 或 uv。以實際執行 Dashboard 的**一般使用者**操作，不要 `sudo bash scripts/setup.sh`；腳本拒絕 root 執行，以免建立 root 擁有的資料／虛擬環境。

腳本不安裝 apt 套件。缺少 Python venv／ensurepip 時會說明需要 `python3-venv`；缺少 ssh、ssh-keygen、ssh-keyscan 時需要 `openssh-client`。先由管理員確認並安裝缺少套件，再重跑。Python 套件依 `requirements.txt` 安裝至專案 `.venv/`，pip／uv 安裝進度會直接顯示。

缺少 Python／venv／ensurepip 或虛擬環境內的 pip 時，腳本會停止並列出以下指令，不會自行執行 apt：

```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv
```

setup 實際使用 `.venv/bin/python -m pip`，並不呼叫系統 pip；系統未安裝 python3-pip、但 venv 內的 pip 可用時，不會因此阻擋安裝。已存在但缺少 pip 的 `.venv` 另提供 `ensurepip --upgrade` 修復指令。若 python3 指向非 Ubuntu 的自訂版本，須替該版本補齊 venv／ensurepip；apt 套件不一定會修復自訂 Python。

### 兩個安裝入口

```bash
# Python venv／pip 版本
bash scripts/setup.sh

# uv venv／uv pip 版本
bash scripts/setup-uv.sh
```

兩者共用密碼、IP、Port、user／system 安裝模式、linger、單元及 HTTP readiness 流程，皆在同一專案 `.venv/` 安裝。

- `setup.sh`：使用 `python3 -m venv` 和 `.venv/bin/python -m pip`，需要 venv／ensurepip 和環境內的 pip。
- `setup-uv.sh`：使用 `uv venv --python <執行腳本的 Python> .venv` 和 `uv pip install --python .venv/bin/python -r requirements.txt`；不要求 pip、ensurepip、python3-venv，也不需要 `--seed`。共同安裝器本身仍需要 python3。uv 指令加上 `--no-python-downloads`，不自動下載另一套 Python。

缺少 uv 或 PATH 找不到 uv 時，腳本會停止並提供兩個選擇，不會自動執行安裝：

```bash
# 選項一：改用一般 Python venv／pip 版本
bash scripts/setup.sh

# 選項二：以一般使用者安裝 uv，不要加 sudo
curl -LsSf https://astral.sh/uv/install.sh | sh
# 安裝後開啟新的終端機，確認 PATH 生效，再執行：
uv --version
bash scripts/setup-uv.sh
```

詳見 [uv 官方安裝說明](https://docs.astral.sh/uv/getting-started/installation/)。

既有有效 `.venv` 會沿用，不會因切换入口而清空。從 uv 切回 venv 版本時，若環境沒有 pip，setup.sh 會提供補齊 pip 的指令；不會自行重建環境。已有資料但缺少 Python 的不完整 `.venv` 會要求先備份／修復，而不是覆蓋。

成功安裝後，`install.json` 的 `backend` 記錄 `venv` 或 `uv`。`bash scripts/reset.sh` 沿用此值；舊版沒有記錄則使用 venv。也可明確選擇 `bash scripts/reset.sh --backend uv` 或 `--backend venv`。移除流程不依賴 uv／pip，只需 Python 3，兩種版本都清除相同的 `.venv`。systemd 啟動直接使用 `.venv/bin/python`，不需要在 PATH 找 uv。

參考 [uv 官方環境說明](https://docs.astral.sh/uv/pip/environments/)。

首次設定 linger、安裝 system 單元或遷移／移除既有 system 單元時需要 sudo 管理員認證。**這不會新增免密碼 sudoers 規則。**

## 快速安裝

公開分享版本只包含通用程式、文件與虛構範例，不含原主機設定。建議位置：

```bash
git clone https://github.com/xthybot/service-harbor.git "$HOME/host-service-dashboard"
cd "$HOME/host-service-dashboard"
bash scripts/setup.sh
```

安裝器使用實際專案絕對路徑，不再強制只能位於上述目錄。專案、設定和資料的管理路徑不得使用 symlink 或含 `..`；同一帳號／設定目錄只管理一套同名 Dashboard。若自訂 `XDG_CONFIG_HOME`，安裝器會核對正在執行的 user manager 的 UnitPath 是否包含實際固定單元目錄 `~/.config/systemd/user/`；不一致時先修正 manager 設定，不會寫入一個 user manager 找不到的單元。移動既有專案前，應先備份、移除舊安裝並在新位置重裝。

安裝時依序詢問：

1. 登入密碼：1–256 個 Unicode 字元，禁止控制字元，保留空白且不自動截斷；輸入隱藏，需再輸入一次確認。重跑 setup 時可留白保留舊密碼。
2. 監聽 IP，首次預設 `0.0.0.0`；接受具體 IPv4／IPv6 位址或 `::`，不接受 CIDR 網段。指定 IP 必須存在於本機。
3. Port，首次預設 `8765`，允許 `1024–65535`，以一般帳號可綁定的非特權埠為範圍。
4. `user` 或 `system` 安裝模式，首次預設 user，重跑時預設既有模式。
5. 顯示執行帳號、單元路徑、監聽位址與資料目錄，輸入 `y` 開始。

程式會逐步顯示進度：前置檢查、linger、venv／pip、停止既有 Dashboard、檢查 IP／Port、寫入設定與單元、daemon-reload、enable／restart、HTTP readiness。最後列出可連線位址，不印出密碼。驗證包含非 root 程序、已啟用單元和連續三次 HTTP `/api/session` 回應；不能只以 enable 指令成功視為完成。

## 兩種 systemd 模式

### user：`~/.config/systemd/user/host-service-dashboard.service`

以目前帳號的 systemd user manager 啟動。安裝器確認 `loginctl enable-linger <帳號>`，必要時僅此步驟使用 sudo，確保未登入也能開機啟動。**不建立 sudoers 候選檔或系統服務控制權限。**

```bash
systemctl --user status host-service-dashboard.service --no-pager
journalctl --user -u host-service-dashboard.service -n 30 --no-pager
loginctl show-user "$(id -un)" -p Linger
```

開機時專案與資料所在磁碟必須已掛載；需要登入後才解鎖的家目錄，無法僅靠 linger 保證登入前啟動。

User 模式的系統 journal 可讀範圍由帳號既有 `adm`／`systemd-journal` 群組等權限決定；腳本不變更群組。權限不足時，部分 system 服務 Log 無法讀取，由管理員自行決定是否授權。

### system：`/etc/systemd/system/host-service-dashboard.service`

由 system manager 管理啟動，但 unit 明確指定 `User=<安裝帳號>`，網站不以 root 執行。sudo 僅用於必要的安裝／systemctl 命令，Python、pip、資料與環境檔始終由一般帳號處理，無須進入 root shell 再切回。

單元為網站程序設定 `SupplementaryGroups=systemd-journal`，可讀取系統 journal；這是讀取全系統 journal 的權限，不會修改帳號本身的群組，也不授予 systemctl 控制權。單元同時設定使用者 bus 位址並依賴 `user@UID.service`；linger 維持本機 user service 查詢能力。

```bash
systemctl status host-service-dashboard.service --no-pager
journalctl -u host-service-dashboard.service -n 30 --no-pager
sudo systemctl restart host-service-dashboard.service
```

安裝到 `/etc` 本身不需要永久免密碼 sudoers。網站的 Dashboard 自身卡片會跟隨 system scope，並停用自身啟停按鈕；其餘 system 服務控制仍受原有 allowlist 和逐項 sudo 授權限制。既有 sudoers 規則不會被安裝器移除或新增。

### 模式切換與失敗處理

重跑 setup 或 reset 可選另一種模式。只處理同一安裝來源的 Dashboard unit，不停止其他被管理的服務。先停止已擁有的舊單元，新單元啟動確認成功後才移除舊模式單元，避免兩套同時運作。

在停止舊 Dashboard 之後發生錯誤，腳本會逐項嘗試停止新單元、復原資料交易、還原環境檔／安裝紀錄／Port 覆寫及原單元設定。出於安全考量舊登入 session 不恢復；若資料復原或單元／設定回復失敗，不會重啟舊服務。請閱讀失敗訊息；sudo 認證失效等問題也可能使回復未完成。pip／uv 套件更新及已啟用 linger 不會自動回退；記憶體中的回復快照只涵蓋執行中失敗，不能保證斷電後整個安裝流程可自動復原。

## 重置（保留服務與金鑰）

```bash
bash scripts/reset.sh
```

重新詢問密碼（不可留白）、監聽 IP、Port 和安裝模式；重建 Dashboard systemd 單元並重新啟動，沿用 setup 的完整 readiness 確認。**保留服務清單、Hosts、URL、Port、最愛與 SSH key**。重置會撤銷舊登入 session，使用者需重新登入；重跑 setup 更換密碼時也會撤銷舊 session。

## 移除（刪除私密資料，保留原始碼）

先自行備份需要保留的服務與 SSH 設定，再執行：

```bash
bash scripts/uninstall.sh
```

腳本先辨識由此專案安裝的 user／system 單元，列出刪除清單，需輸入完整 `REMOVE` 才執行：

- 停止、停用並刪除 Dashboard 單元，重新載入對應 systemd manager。
- 完成資料清除後才刪除密碼環境檔與 install.json；移除舊版 setup 產生的本機 sudoers **候選檔**。中途失敗保留原資料位置紀錄，重跑會繼續。
- 刪除專案 `data/`（包含 Hosts、服務、session、SSH 私鑰及 known_hosts）與 `.venv/`。
- 自訂 `DASHBOARD_DATA_DIR` 只刪已知 Dashboard JSON、專用 SSH key 與 hosts.json 中登記的 pinned known_hosts，不遞迴刪除外部目錄或混用 ssh/ 的未知檔案。
- 原始碼、其他服務、系統 journal、現有 `/etc/sudoers.d` 規則、帳號群組、linger 與防火牆設定皆保留。

不自動停用 linger，因為該帳號的其他 user services 可能依賴它。此版未建立 sudoers，故不刪除管理員既有的權限設定。遠端主機 `authorized_keys` 的舊公鑰需自行移除；重新安裝產生的新 key 必須重新部署至遠端。瀏覽器 localStorage 的追蹤倒數屬於瀏覽器資料，主機移除腳本不會清除它。

清理前核對 data 目錄的 `.dashboard-owner.json` 所屬專案／帳號／UID／路徑與 install.json、dashboard.env 的 DATA_DIR。舊安裝若尚無 ownership 標記，先停止 Dashboard、核對資料路徑，再執行 `python3 scripts/lifecycle.py adopt-data`，輸入 `ADOPT` 後才可重跑 setup／reset／uninstall。這一步不會清除資料。若檔案路徑含 `..`、symlink、共享系統根目錄，或 ENV／receipt 不一致，腳本會拒絕執行；先人工核對並修正原始記錄。

若需離線撤銷所有登入：先停止 Dashboard，再執行 `python3 scripts/lifecycle.py revoke-sessions`。此命令先經共用儲存層完成未結束交易的復原，再寫入空 sessions.json；不可直接刪交易日誌。

再次安裝只需執行 `bash scripts/setup.sh`。不需要刪除 git repository。

## LAN 與分享注意事項

`0.0.0.0` 代表監聽所有 IPv4 介面；用安裝結尾列出的實際 LAN IP 連線，不要把 0.0.0.0 當成其他電腦連線目的地。指定 127.0.0.1 時僅能從本機連線。腳本不調整防火牆；有啟用 UFW 的主機，由管理員依實際可信任子網放行所選 Port，例如：

```bash
sudo ufw allow from 192.168.1.0/24 to any port 8765 proto tcp
```

新安裝只有 Dashboard 自身。可透過 Add service 新增，或修改 `examples/services.json` 的虛構設定後匯入；不會安裝、啟動範例 unit。既有主機的私密 `local-catalog.json` 不隨 Git 發布。獨立裝置監控是另外部署的選用服務，並不隨安裝器自動建立。

私密資料不包含在 GitHub 程式碼中；請勿分享 `.venv`、密碼環境檔、`data/` 或含金鑰的備份。設定檔格式、讀取權限與控制授權詳見 [設定參考](CONFIGURATION.zh-TW.md)。

## 目前驗證範圍

此版在 Ubuntu 24.04.3 LTS、Python 3.12.3 上執行隔離的 lifecycle 模擬測試；涵蓋 venv／uv 路徑、systemd/sudo 模擬、清理失敗重試及回復錯誤。未在正式主機執行完整重裝、模式遷移、移除或開機後登入前啟動測試。其他 Ubuntu／Python 版本需先於一次性環境驗證相同流程；請勿將「Ubuntu」概括為全部版本已驗證。
