# SSH 主機與服務管理

## 操作流程

1. 開啟 `http://<Dashboard 主機 IP>:8765/#hosts`，複製 Dashboard public key（或 Download .pub）。初次安裝還沒有金鑰時按 Generate key。
2. 在遠端主機以預定 SSH 帳號建立 `~/.ssh/authorized_keys`，追加公鑰。不要複製 Dashboard 私鑰，也不要把金鑰／登入資料寫進 repository。
3. Hosts → Add host：在置中的視窗填名稱、IP／hostname、SSH username、SSH port。使用一般 Linux 帳號，不接受 root。
4. Verify fingerprint：網頁會掃描 SSH 主機公鑰，但掃描本身不能證明對方身分。從遠端主機 console 或已信任的管理管道核對 SHA256 指紋，勾選確認後 Trust host。
5. Check connection：確認免密碼 SSH，並檢查 systemd 與 system journal 可讀性。User journal 權限依該帳號而定；可透過實際服務 Log 確認。
6. Add service → Host 欄選 This host 或已儲存的遠端主機。遠端有 unit 的服務須先確認主機指紋；再填選用 unit、user/system scope、名稱、分類與選填 Open URL → Add service。其他機器須先到 Hosts 新增。
7. Services 可依主機篩選，點卡片查看 status／即時 journal 或進行控制。Hosts 卡片顯示最近一次明確連線檢查，以及目前服務查詢的狀態。

服務註冊只接管 Dashboard 清單，不會建立、啟動或 enable 遠端單元。填入 unit 時會唯讀檢查單元存在；連線失敗／不存在／masked 時不會加入。需要監控或控制時，先部署程式及 systemd unit，再於 Dashboard 註冊。

Services 的 JSON 匯入是離線還原流程：可先註冊尚未信任的新主機及其服務，待在 Hosts 核對指紋後再連線。匯入本身不驗證 unit、不中斷或啟動服務；主機比對使用儲存位址、SSH 使用者名稱及 Port，JSON 不含主機顯示名稱或 SSH 金鑰。詳細欄位與重複處理見 [設定參考](CONFIGURATION.zh-TW.md#服務設定-json-匯出與匯入)。

This host／Remote SSH 的 systemd unit 可留白，保留主機、名稱及選填 URL。沒有 unit 時不查詢 systemd、不執行 SSH 服務查詢、不提供啟動／停止／重啟或 journal 功能；詳細視窗顯示 Details。有 URL 顯示 Linked，沒有 URL 顯示 Unmanaged；在 Services 修改 URL 後狀態同步更新。Remote SSH 仍需選擇已新增的主機，但僅有 unit 的項目需要先確認主機指紋。

Hosts 的公鑰位於主機清單旁的小面板（小螢幕放到清單下方），提供 Copy key 與 Download .pub。Add host 旁的 SSH guide 會開啟說明視窗，列出 SSH 金鑰、journal／user manager／精確 sudoers 權限、實際讀取與控制指令，以及 key 的權限範圍。

Add service 使用單一「欄位名稱｜輸入框」表單，不分步驟；Host 欄整合本機、已註冊的遠端主機及純外部網址選項。Add SSH host／Edit SSH host 視窗亦使用相同左右欄排列。新增服務僅保留 Add service 按鈕，已移除清空、匯出與草稿功能；Description 隨文字與視窗寬度自動增高，公鑰文字框亦同，不需手動拉高。

## 將公鑰安裝到遠端

以下在遠端以對應帳號執行，追加網頁所顯示的完整公鑰行；不覆蓋既有 authorized_keys：

```bash
install -d -m 700 "$HOME/.ssh"
touch "$HOME/.ssh/authorized_keys"
chmod 600 "$HOME/.ssh/authorized_keys"
nano "$HOME/.ssh/authorized_keys"
```

可在該公鑰行前加 `restrict `（含空格），限制 PTY、port／agent forwarding 等功能，同時允許執行命令。這不是任意命令白名單：SSH key 對應帳號仍可執行其本身有權限的命令，請使用適當的專用一般帳號。Dashboard 後端只產生 systemctl、journalctl 與 id 等固定命令，不提供任意 shell 執行 API。

比較預設 Ed25519 host key 指紋：

```bash
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

若網頁顯示 ecdsa 或 rsa，改用對應的 ssh_host_ecdsa_key.pub 或 ssh_host_rsa_key.pub。主機位址／SSH port 改變會撤銷既有信任；遠端更換 host key 時，StrictHostKeyChecking 會拒絕連線，核對新指紋後才重新信任。

主機位址或 SSH Port 變更時，Dashboard 會先把主機寫成未信任且記錄待清理狀態，再刪除該主機 ID 對應的 pin。若刪檔或最後的資料寫入失敗，主機仍保留在清單，不能使用 SSH；修正檔案問題後，對同一主機重按 Save 即會重試清理，之後必須重新掃描並核對指紋。若第一次資料寫入失敗，原主機與 pin 都維持原狀。重新信任既有主機時也會先撤銷舊信任，再替換 pin；失敗不會讓新 pin 配上舊的 trusted 狀態。

刪除主機時也會先保存未信任且待刪除的主機紀錄，刪除精確的 `<主機 ID>.known_hosts` 後才移除主機資料。若 pin 刪除失敗，按原主機的 Remove host 重試；若刪檔後程序中斷，重試也可完成主機移除。待刪除的主機 ID 仍在 `hosts.json`，因此完整 uninstall 可依其登記資訊清理 pin。清理未完成時，不會自動重新信任主機；其他主機的 pin、未知檔案及 Dashboard 私鑰不在此操作範圍。

## Journal 與控制權限

user scope 使用 SSH 帳號的 `systemctl --user` 與 `journalctl --user`。帳號需要可用的 user manager；若要登出後仍有常駐服務，可由管理員執行：

```bash
sudo loginctl enable-linger dashboard
```

若登入環境沒有 XDG_RUNTIME_DIR／user bus，應在遠端 SSH／PAM 登入設定提供正確使用者環境。不要把 root 的 user manager 當成該帳號的 manager。

系統 journal 一般不需要 sudo 執行，但帳號需有讀取權限。管理員可執行：

```bash
sudo usermod -aG systemd-journal dashboard
```

Dashboard 每次操作建立新的 SSH command session，新連線會使用更新後的群組。Check connection 的 journal 指標是 system journal 的保守檢查；ACL、缺少 journal 或權限警告可能使它顯示 limited／unverified，而不是宣稱完整可讀。即使系統 journal 權限不足，該帳號的 user journal 仍可能可讀。

系統服務 Start／Stop／Restart 使用 `sudo -n`，不提示密碼。由管理員編輯並驗證精確 sudoers 規則，例如：

```bash
sudo visudo -f /etc/sudoers.d/host-dashboard
```

內容（替換帳號與真實 unit；每個單元都要分別列出）：

```sudoers
dashboard ALL=(root) NOPASSWD: /usr/bin/systemctl start example.service, /usr/bin/systemctl stop example.service, /usr/bin/systemctl restart example.service
```

```bash
sudo chmod 0440 /etc/sudoers.d/host-dashboard
sudo visudo -c
```

不能使用任意 systemctl／shell 的通用 sudo 權限。user scope 控制不使用 sudo。本機新增的 system scope 服務也需要相應的精確 sudoers 規則；Web 不會自動提升權限或安裝規則。

## Dashboard 在遠端執行的指令

下列 `UNIT` 是已註冊的 systemd unit，`N` 是 Log 行數。對同一主機的多個 unit，狀態查詢會合併為單次 `systemctl show`。新增有 unit 的服務時，也會用相同的 `show` 指令唯讀確認其存在。

Check connection：

```bash
/usr/bin/id
/usr/bin/systemctl --version
/usr/bin/journalctl --system --no-pager -n 1 -o short-iso
```

讀取 System／User 服務狀態與啟動時間：

```bash
/usr/bin/systemctl show --no-pager --property=Id,Description,ActiveState,SubState,ActiveEnterTimestamp,FragmentPath,LoadState UNIT
/usr/bin/systemctl --user show --no-pager --property=Id,Description,ActiveState,SubState,ActiveEnterTimestamp,FragmentPath,LoadState UNIT
```

查看 Status：

```bash
/usr/bin/systemctl status --no-pager -n 35 UNIT
/usr/bin/systemctl --user status --no-pager -n 35 UNIT
```

讀取最近 Log／追蹤即時 Log：

```bash
/usr/bin/journalctl -u UNIT -n N --no-pager -o short-iso
/usr/bin/journalctl -u UNIT -n N --no-pager -o short-iso --follow
```

User scope 在 `journalctl` 後加 `--user`。System scope 的 Start／Stop／Restart 使用精確 sudoers 權限；User scope 使用 SSH 帳號權限：

```bash
/usr/bin/systemctl --user start UNIT
/usr/bin/systemctl --user stop UNIT
/usr/bin/systemctl --user restart UNIT
/usr/bin/sudo -n /usr/bin/systemctl start UNIT
/usr/bin/sudo -n /usr/bin/systemctl stop UNIT
/usr/bin/sudo -n /usr/bin/systemctl restart UNIT
```

Open ports 對手動設定與服務已設定的 Port，由 Dashboard 主機直接嘗試 TCP 連線；不透過 SSH 執行 Port 指令。掃描主機指紋的 `ssh-keyscan` 在 Dashboard 本機執行；Open URL 由瀏覽器開啟。

## 執行模式與限制

- 指令使用 SSH `-T -n -a -x`、`BatchMode=yes`、`IdentitiesOnly=yes`、`StrictHostKeyChecking=yes`，禁用 forwarding、忽略其他 SSH config 與全域 known_hosts，只用專用 identity／per-host known_hosts。
- 不開啟互動式 shell、不配置終端，也不要求密碼或私鑰 passphrase。OpenSSH 協定會將固定命令交給遠端帳號的非互動式命令處理；一般遠端 shell 可能由 sshd 內部使用，但沒有供使用者操作的登入 shell。
- 後端遠端命令以 shlex.join 編碼，單元、帳號、位址及 port 皆驗證，沒有任意 shell 字串輸入。
- `journalctl --follow` 是持續執行的一條指令；瀏覽器用 SSE 接收輸出。Pause／關閉 Log／離開 drawer／登出會終止該 SSH 子程序，連線中斷由 keepalive 偵測。
- 沒有每三分鐘的全站刷新；點服務會單次查詢該 unit，頂端開啟即時後每三秒只查目前選取項目。篩選及明確刷新仍會進行一次查詢；全量查詢時遠端 host/scope 分組批次查詢。Unavailable 表示無法查詢，不視為 Stopped。External URL 顯示 Linked，不推定實際執行狀態。
- Open 直接讓使用者瀏覽器連到目標 URL，不建立 SSH tunnel。Remote SSH 服務的 Open URL 需明確指定。
- External URL 服務沒有 journal 或控制。有 unit 的 Remote SSH 提供 systemd status／近期與即時 journal／控制，但不是遠端硬體 I/O monitor。
- 上限 50 個遠端主機、200 個自訂服務。多個離線主機可能延長狀態刷新；查詢有 SSH connection timeout 與 command timeout。

## 本機儲存與備份

`data/hosts.json` 保存主機、信任指紋及最近檢查；`data/registered-services.json` 保存新服務。`data/ssh/` 是 0700，私鑰 `dashboard_ed25519`、公鑰 `.pub` 與各主機 `.known_hosts` 為 0600。金鑰屬執行 Dashboard 的一般帳號，私鑰沒有 passphrase，以便常駐程序非互動使用；沒有私鑰下載 API。

Git 忽略整個 data/，因此 GitHub 不備份金鑰、主機與服務設定。本機 data 備份現在也包含私鑰，必須私密保管。遷移／還原需維持原帳號 ownership 與權限，重新啟動 Dashboard；若換新金鑰，所有遠端 authorized_keys 都要更新。

刪除服務僅移除 Dashboard 註冊，不會 stop／disable／刪除 unit。刪除主機前必須先移除它的自訂服務；刪主機同時移除本機 pin，不會從遠端撤銷 authorized_keys。停用存取需自行移除遠端公鑰行。

## 跨主機 Open ports

每個服務可手動設定 1–65535 的 Service port；Open URL 是獨立欄位，公開網域的 80／443 不會自動變成服務 port。已新增的服務可在 Services 編輯視窗修改 port。Open ports 列出已設定 port 的本機與遠端服務，以 Dashboard 主機的 TCP 連線結果顯示 Open／Unreachable；未設定 port 的舊服務可透過編輯視窗補上。沒有 systemd unit 的連結不列入。

Port 數字仍來自設定值，狀態則是從 Dashboard 主機出發的 TCP 連線結果。Dashboard 不執行本機或遠端 `ss`、`netstat` 等 socket 查詢；遠端 systemd 狀態仍透過 `systemctl show` 取得。主機上的數字代表此次檢查可連通的已記錄 Port 數量；零不代表該主機沒有其他監聽埠，也不保證所有網路位置都無法連入。

Open ports 中來自 Services 的 Port 只能查看服務、主機與 Port；右上角 **View service** 會切到 Services 並開啟對應服務詳情。要修改或取消此 Port，從 Services 詳情的編輯視窗操作。另行用 Open ports → Add port 建立的手動紀錄則可直接在 Open ports 編輯或刪除；這些紀錄不會建立 systemd unit，也不隨 Services 的 JSON 匯出。
