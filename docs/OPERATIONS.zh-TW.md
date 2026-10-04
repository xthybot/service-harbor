# 維運、備份與還原

## 安裝模式提醒

下方既有範例以 user 模式為主。system 模式請改用 `sudo systemctl <動作> host-service-dashboard.service` 和 `journalctl -u host-service-dashboard.service`，備份 unit 路徑改為 `/etc/systemd/system/host-service-dashboard.service`。密碼及資料仍屬於安裝帳號。互動重置用 `bash scripts/reset.sh`，完全移除用 `bash scripts/uninstall.sh`；詳細範圍見 [安裝說明](INSTALLATION.zh-TW.md)。


## 日常操作

```bash
systemctl --user status host-service-dashboard.service --no-pager
journalctl --user -u host-service-dashboard.service -n 50 --no-pager
systemctl status host-device-monitor.service --no-pager
journalctl -u host-device-monitor.service -n 50 --no-pager -o cat
```

網站為 `http://<LAN-IP>:8765`。獨立監控檢視器若另行安裝，網址可為 `http://<LAN-IP>:8766/`；Dashboard 需額外註冊該監控服務才會顯示其卡片。操作服務前使用頁面確認框，注意停止或重啟 Dashboard 本身會短暫中斷瀏覽器連線。

## 更新與推送

```bash
cd "$HOME/host-service-dashboard"
git status --short --branch
git fetch origin
git log --oneline --decorate -5
# 確認本機修改與遠端差異後，再依工作流程更新 main。
systemctl --user restart host-service-dashboard.service
```

有未提交變更時先檢查並保存，避免覆蓋現場修改。若 requirements.txt 改變，再於一般帳號的 `.venv` 安裝依賴；若 unit 或安裝位置改變，使用 `bash scripts/setup.sh` 或 `bash scripts/reset.sh` 由安裝器生成並驗證單元；不可直接安裝含 `@...@` 的範本。監控原始碼或 system unit 改變時，需要：

```bash
cd "$HOME/host-device-monitor"
sudo ./scripts/install-collector.sh
```

只重啟 monitor 不會把 `~/host-device-monitor` 原始碼複製到 `/usr/local`。更新後重載瀏覽器；前端修改時要更新 index.html 中的靜態資源版本 query，避免舊檔案快取。

本機 Git 提交不會自動推送或定時備份。開發應在新分支進行，檢查通過後合併至本機 `main`。只有明確要求推送／備份時，才使用 `gh` 核對 repository，並透過 SSH push。以下 `<本次修改路徑>` 與 `<工作分支>` 請替換為實際值：

```bash
git diff --check
git status --short
git add -- <本次修改路徑>
git diff --cached --stat
git commit -m "Describe the change"
git switch main
git merge --ff-only <工作分支>
gh repo view xthybot/service-harbor
git remote -v
git push origin main
```

推送前確認 `origin` 的 push URL 為 `git@github.com:xthybot/service-harbor.git`，staged 清單沒有本機資料、環境檔或憑證。不要 force push；遠端 main 有新提交時先協調並整合。純文件修改不需重啟 Dashboard。

## 備份範圍

GitHub repository 保存原始碼、文件、`.env.example`、systemd 和 sudoers 範本。它不保存虛擬環境、登入密碼、sessions、服務別名、最愛、自訂 URL、書籤、實際已安裝 unit、journal、或其他服務本身的程式／資料。

這些本機設定需要額外的私密備份。以下範例在主機本機建立 archive，內含密碼，應存放至有存取控制或加密的儲存位置，不要推送到 GitHub：

```bash
backup_dir="$HOME/host-dashboard-backups/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$backup_dir"
chmod 700 "$backup_dir"
(
  set -e
  trap 'systemctl --user start host-service-dashboard.service' EXIT
  systemctl --user stop host-service-dashboard.service
  tar --exclude='host-service-dashboard/data/sessions.json' --exclude='host-service-dashboard/data/.json-transaction.json' -czf "$backup_dir/dashboard-local.tgz" -C "$HOME" host-service-dashboard/data .config/host-service-dashboard .config/systemd/user/host-service-dashboard.service
  chmod 600 "$backup_dir/dashboard-local.tgz"
)
```

先確認各路徑存在。停止 Dashboard 可避免 JSON 在備份過程中更新；上述子程序的 trap 會在結束或失敗時重新啟動服務。此範例預設資料與設定路徑；自訂 DATA_DIR／XDG_CONFIG_HOME 時需調整。session 不備份，還原後重新登入。備份前先停止服務並確認沒有待復原或損壞的 JSON 交易；若看到 `.json-transaction.json`，先解決復原錯誤，不要刪除該日誌規避錯誤。

journal 由系統 journald 管理，其保存期限與是否持久化不由 repository 控制。需要長期保存監控事件時，管理員另行制定 journal 保存／匯出策略。

## 還原

同機原路徑還原時，先選擇可信任的本機 archive 並檢查 `tar -tzf <archive>` 清單，再停止 Dashboard；先經儲存層完成 recovery，確認沒有損壞交易日誌。解壓會覆蓋對應檔案，還原前先備份目前版本。restore 完成後由安裝器重新生成 unit，再離線撤銷登入。跨主機遷移另見下節。

```bash
systemctl --user stop host-service-dashboard.service
tar -xzf /absolute/path/to/dashboard-local.tgz -C "$HOME"
chmod 600 "$HOME/.config/host-service-dashboard/dashboard.env"
chmod 700 "$HOME/host-service-dashboard/data"
python3 scripts/lifecycle.py revoke-sessions
bash scripts/setup.sh
```

### 跨主機遷移

先在新主機以新帳號 clone 原始碼並執行 setup 產生新環境、unit 及 receipt；不可直接覆寫舊機的 UID、絕對路徑、unit 或 install.json。停用服務後，只挑選並私密搬移服務、Hosts、別名、URL、Port、最愛等業務 JSON；主機信任指紋與 SSH key 須逐一核對，必要時建立新專用 key 並重新部署公鑰。若資料根不是乾淨目錄，先依安裝文件進行 ownership 核對。完成後用安裝器重建 systemd 設定，離線撤銷 session，再核對 catalog、Port、linger、journal 權限及 LAN 防火牆。實際 root-owned sudoers 與監控服務須另外建立。

## 密碼與撤銷登入

在本機私下編輯 `~/.config/host-service-dashboard/dashboard.env` 的 DASHBOARD_PASSWORD，保持 0600，再重新啟動 Dashboard。不要把實際密碼寫入 repo、issue 或命令日誌。

密碼更新不會自動撤銷已存在的 session。需要撤銷全部登入時：

```bash
systemctl --user stop host-service-dashboard.service
python3 scripts/lifecycle.py revoke-sessions
systemctl --user start host-service-dashboard.service
```

此命令從 ENV／install.json 辨識原 DATA_DIR，核對服務已停止與資料歸屬，先完成交易復原，再以共用儲存層清空 session。復原失敗時會保留交易日誌並停止撤銷，需先修復資料；不可只刪 sessions.json，以免舊交易將登入還原。下次登入驗證立即使用最新儲存資料；既有 SSE 在正常情況下最多五秒後停止。

## 故障排查

| 現象 | 檢查與處理 |
| --- | --- |
| LAN 連不到 | user unit、ss listener、正確 LAN IP、可信任子網防火牆 |
| 登入反覆失敗 | 私密環境檔、HTTP／Secure cookie、代理 scheme／host、八次失敗／60 秒的限制 |
| API 403 | 寫入操作是否由同源頁面送出，反向代理的 host／scheme 是否正確 |
| 系統服務操作需要密碼 | sudoers 候選檔是否替換帳號、visudo 是否通過、單元與動作是否精確列出 |
| 無 system journal | 執行帳號 journal 讀取權；sudoers 不授權 journal |
| JSON 寫入失敗 | 檔案擁有者、目錄權限、DATA_DIR 與 ReadWritePaths 是否一致 |
| Open ports 的服務 Port 無法編輯 | 這類 Port 在 Open ports 是唯讀；按 View service，於 Services 編輯或移除 Port。手動 Port 仍可在 Open ports 編輯。 |
| 開機後 Dashboard 未啟動 | user unit enabled 與帳號 Linger=yes |
| monitor 狂重啟 | status 的 SubState／NRestarts 和修正版啟動之後的 journal；詳見監控文件 |

不能只因 `systemctl --failed` 顯示零失敗單元就認定健康；auto-restart 中的單元可能處於 activating。檢查 active／substate、穩定 PID，以及短時間內 NRestarts 是否繼續增加。

## SSH 設定備份

data/ 備份現在還包含主機、已註冊服務、私鑰與 pinned known_hosts；沿用上述本機備份方式時，備份檔須私密保存，勿推送 GitHub。還原 data/ssh 的 ownership 為 Dashboard 帳號、目錄 0700、key／known_hosts 0600。刪除主機註冊不會移除遠端 authorized_keys 的公鑰行；撤銷存取需在遠端移除。詳見 [SSH 主機管理](SSH_HOSTS.zh-TW.md)。

公開分享 repository 不包含私人維運歷史。請勿直接把私人 repository 分支推送到公開版；僅從審查過、不含 data/ 和歷史規劃文件的快照發布。
