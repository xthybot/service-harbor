# 設定參考

## 環境變數

兩種模式都讀取安裝帳號的 `~/.config/host-service-dashboard/dashboard.env`；若設定 `XDG_CONFIG_HOME`，則位於該目錄下的 `host-service-dashboard/dashboard.env`，生成單元使用其實際絕對路徑。檔案權限 0600、設定目錄 0700。`.env.example` 只是範例，不會自動載入專案 `.env`。

| 變數 | 首次預設／必要性 | 用途 |
| --- | --- | --- |
| DASHBOARD_PASSWORD | 必須設定 | setup 隱藏輸入及確認；重跑可留白保留，reset 必須重設 |
| DASHBOARD_BIND | 0.0.0.0 | Uvicorn 監聽 IP，不是 CIDR；支援 IPv4／IPv6 |
| DASHBOARD_PORT | 8765 | 監聽 Port，安裝器接受 1024–65535 |
| DASHBOARD_INSTALL_MODE | user | 自身 Dashboard catalog 的 scope，隨 user／system 安裝寫入 |
| DASHBOARD_COOKIE_SECURE | 0 | 設為 1 時 cookie 僅經 HTTPS 傳送，需已配置反向代理 |
| DASHBOARD_DATA_DIR | 專案下 data/ | 私密 JSON 和 SSH key 的絕對路徑 |

安裝器不會 shell source／eval 環境檔。支援單行 KEY=value 或引號值，輸出使用 systemd EnvironmentFile 引號格式；多行值與不支援的舊格式會明確報錯，需先整理再安裝。密碼不放進命令列、不輸出至終端。

`install.json` 記錄模式、執行帳號、專案、資料路徑及安裝工具 backend（venv／uv），不含密碼，權限 0600。setup／reset 會檢查同名 unit 的來源；不覆寫其他專案建立的單元。可辨識舊版位於 `~/host-service-dashboard` 的 user 範本單元。不要手改安裝紀錄或直接搬動已安裝的專案。

## 監聽位址、Port 與安裝模式

使用同一套互動流程修改設定：

```bash
bash scripts/setup.sh
# 或必須重新設定密碼、重建單元並撤銷登入：
bash scripts/reset.sh
```

重跑會以既有位址、Port、模式作為預設值。setup.sh 使用 venv／pip；setup-uv.sh 使用 uv venv／uv pip。reset.sh 沿用 install.json 的 backend（舊安裝預設 venv），也可用 `--backend uv` 或 `--backend venv` 指定。安裝器依 `systemd/host-service-dashboard.service` 參數化範本產生真正單元，不能直接將帶有 `@...@` 的範本 install 到 systemd。

- user 單元固定在 `~/.config/systemd/user/host-service-dashboard.service`；環境檔可使用自訂 XDG_CONFIG_HOME。
- system 單元在 `/etc/systemd/system/host-service-dashboard.service`，明確指定安裝帳號的 User／Group、使用者 bus 和程序專屬 systemd-journal 附加群組。
- 兩種模式都保證 linger 已啟用；程序不以 root 執行，不生成 sudoers 候選檔／免密碼授權。
- 服務自身的 catalog scope／預設 Port 讀取安裝環境；既有自身 Port 覆寫會在 setup 時同步為新 Port，其他服務資料不改動。公開 Open URL 覆寫仍保留。
- 頁尾 Port 顯示瀏覽器實際連線的 Port，使用反向代理時可能與後端監聽埠不同。

手動編輯環境檔後，需重啟對應模式；改 DATA_DIR 還需重建 unit 的 ReadWritePaths。建議用 setup 完成同步。若既有安裝沒有 DASHBOARD_BIND／PORT 環境變數，setup 以首次預設值詢問；自訂過舊 ExecStart 的使用者需重新輸入實際值。

```bash
# user 模式
systemctl --user restart host-service-dashboard.service
# system 模式
sudo systemctl restart host-service-dashboard.service
```

重置保留服務／Hosts／SSH key，移除會清除私密資料與 `.venv`，保留原始碼；自訂資料目錄只清除已知 Dashboard 檔案及 ssh/。詳見 [安裝、重置與移除](INSTALLATION.zh-TW.md)。

## 服務清單與權限

公開版內建清單只有 Dashboard 自身；既有私密 `data/local-catalog.json` 可保存本機固定服務，不隨 Git 發布。`app/catalog.py` 合併每個單元的 `id`、`name`、`scope`（user／system）、`description`、`category`、`web` 與已知的預設 `port`。其他服務需手動新增或匯入；Services 編輯視窗的 Port 設定會覆蓋預設值。UI 註冊的服務保存於 `data/registered-services.json`，會合併至 allowlist。只有 allowlist 內單元可操作。手動新增服務可在詳情編輯與 Add service 相同的欄位；內建服務的 Host、scope、unit 固定，分類與描述覆寫存於私密的 `data/service-metadata.json`。Port 由新增服務或 Services 編輯視窗手動設定，儲存於服務註冊資料或 `data/service-ports.json`；Open ports 對所有已設定 Port 嘗試 TCP 連線，與 systemd 執行狀態分開顯示。來自 Services 的 Port 在 Open ports 僅顯示唯讀詳情，右上角 **View service** 可前往對應服務；Port 修改或移除要到 Services 編輯視窗。手動 Port 的新增、修改與刪除仍由 Open ports 管理。對服務 Port 刪除只寫入空 Port 覆寫，不會移除服務或停止 unit。

Open ports 的「Add port」可另外儲存非 systemd 服務，資料在私密的 `data/manual-ports.json`。Host 可選本機、Hosts 中已登記的主機，或填入其他 IP／hostname；「Service / source」可填 unit、檔案路徑、網址或留空。新增與修改前按「Check port」，會從 Dashboard 主機發起 TCP 連線檢查（每個候選位址連線逾時一秒，DNS 解析另計），顯示 Open／Unreachable、是否已有同主機同 Port 紀錄。開啟網站／Open ports 頁或明確刷新時會重新檢查；選取一列時只檢查該 Port 一次，啟用頂端「即時」後每三秒只檢查該列。Open 只代表 TCP 連得上，不代表 HTTP 回應正常；Unreachable 也可能是防火牆或路由限制。本機選項檢查 `127.0.0.1`，若服務只綁定其他介面，請用「Other IP / hostname」填實際位址。這些 Port 檢查不使用 SSH、不要求 sudo，也不執行遠端命令。重複 Port 可在確認後保留兩筆紀錄；刪除 Hosts 主機前，需先移除引用它的手動 Port 紀錄。手動 Port 紀錄屬於網路清單，與 Services 註冊和其 JSON 匯入／匯出分開。

安裝器不自動授權以下操作；既有 sudoers 保留不動。公開版不預載其他 system 單元；私密舊清單的 control_allowed 設定會保留。新增需要啟停權限的 system 單元時，在 `sudoers/host-service-dashboard` 分別加入確切的 start、stop、restart 指令，重新產生候選規則、visudo 驗證並由管理員安裝。模板中的 `@DASHBOARD_USER@` 必須替換為實際帳號；禁止直接安裝未替換的範本。

```bash
rule_tmp="$(mktemp "$HOME/.config/host-service-dashboard/host-service-dashboard.sudoers.XXXXXX")"
sed "s/@DASHBOARD_USER@/$(id -un)/g" sudoers/host-service-dashboard > "$rule_tmp"
chmod 0440 "$rule_tmp"
mv -f -- "$rule_tmp" "$HOME/.config/host-service-dashboard/host-service-dashboard.sudoers"
sudo visudo -cf "$HOME/.config/host-service-dashboard/host-service-dashboard.sudoers"
sudo install -o root -g root -m 0440 "$HOME/.config/host-service-dashboard/host-service-dashboard.sudoers" /etc/sudoers.d/host-service-dashboard
sudo visudo -c
systemctl --user restart host-service-dashboard.service
```

不得加入 systemctl 萬用字元或免密任意 shell。user 單元使用執行帳號自己的 systemctl --user，不需要 sudo。

## 網頁設定

Overview 使用現有查詢結果顯示 Needs attention（Failed、Unavailable 服務與 TCP Unreachable／Unavailable）、最愛、主機與 Port 摘要。Stopped 不列為服務異常。異常預設最多五筆、最愛最多六個，可展開全部。首頁搜尋只搜尋已載入資料，支援服務名稱／unit／主機／位址／Port；選結果會打開詳情或對應清單。主機的服務查詢結果和上次 SSH Check connection 結果分別標示，兩者不是主機存活保證。各筆資料有獨立檢查時間；沒有第一輪結果前顯示等待狀態。

原首頁的 User／System／Favorites 篩選移到 Services。桌面版 Needs attention 佔左側 2/3，右側 1/3 為 Tracking 限時追蹤清單；窄螢幕改為上下排列。下方左側依序為 Hosts 和 TCP ports，右側 Favorites 採橫向清單；僅影響 Overview。Tracking 與 Needs attention 並排時等高，窄螢幕上下排列時依內容高度顯示。新增和匯入／匯出仍使用各頁面的入口。

服務卡片上的鉛筆按鈕已移除；點開卡片後，從 detail drawer 右上角的鉛筆開啟編輯視窗，會預填目前設定。手動新增服務可改 Host、scope、unit、名稱、分類、描述、Port、Open URL 與最愛；內建服務的 Host、scope、unit 固定。清空自訂網址後，web 服務會回復使用 Dashboard hostname 與已設定的 Port。顯示名稱不會改 systemd unit 名稱。

網址接受 HTTP／HTTPS，拒絕內含帳密的 URL。星號控制最愛；網址統一在 Services 編輯。新增服務頁面可正式註冊現有的本機／遠端單元或外部 URL；Remote SSH 主機需先在 Hosts 建立並信任。

## 本機資料

| 檔案 | 內容 |
| --- | --- |
| data/hosts.json | SSH 主機設定、fingerprint 與最近檢查 |
| data/registered-services.json | 自訂本機／遠端服務與外部 URL |
| data/service-metadata.json | 內建服務的分類與描述覆寫；首次修改時才建立 |
| data/service-ports.json | 服務 Port 覆寫；`null` 可取消 catalog 預設 Port |
| data/manual-ports.json | Open ports 手動新增的 Port；首次新增時才建立 |
| data/ssh/ | 專用 SSH identity 與各主機 known_hosts，私密保管 |
| data/bookmarks.json | 歷史書籤資料，現行介面／API 不讀取；僅供手動遷移參考 |
| data/service-names.json | 服務別名 |
| data/service-open-urls.json | 服務 Open 網址覆寫 |
| data/service-favorites.json | 最愛單元 ID |
| data/sessions.json | session token 雜湊與到期時間 |

檔案於需要時建立，JSON 寫入使用暫存檔與原子替換。不要在服務執行時手動編輯 session 檔，因為它也有程序記憶體快取。整個 data/ 被 Git 忽略；保管方式見維運文件。

## 刷新與登入

沒有三分鐘全站定時刷新。初次登入、進入 Open ports、按 Refresh、儲存設定或篩選時仍可進行一次全量刷新。每個頁面共用的頂端切換鈕標示「Not live／Live」，預設為 Not live；點服務卡片會單次查詢該 unit，若有設定 Port 也做 TCP 連線，詳情視窗顯示這次服務狀態查詢時間；點 Port 列則只檢查該 Port，選取時底色停留約一秒，再於約一秒內淡出。Live 模式每 3 秒只查目前選取項目；切換項目、關閉服務詳情或離開頁面會停止舊輪詢。搜尋輸入有短暫 debounce。detail drawer 的 journal SSE 由 Log 頁籤自行管理，與頂端 Live 切換分開；Not live 時開啟有 unit 的服務詳情仍會追蹤 Log，可按 Pause。獨立 Device Monitor 檢視器也使用 SSE。

登入 cookie 為 HttpOnly、SameSite=Strict，有效期七天，token 雜湊持久化至 sessions.json。改密碼不會自動撤銷舊 session；需要全部重新登入時依維運文件清除 session。

反向代理必須讓 backend 正確認知外部 scheme、host 與 Origin；寫入 API 有同源檢查。只啟用 Secure cookie 而仍使用 HTTP 會造成登入 cookie 無法送出。若需要代理部署，先依實際代理配置驗證登入、操作確認與 SSE。

SSH 主機、公鑰、遠端權限與服務新增流程見 [SSH 主機管理](SSH_HOSTS.zh-TW.md)。內建服務仍可編輯 catalog；UI 新註冊服務保存於 data/registered-services.json，不需重啟。

## 服務設定 JSON 匯出與匯入

Services 頁的 Export JSON 可選全部服務、單一類別、最愛、手動新增或單一服務；單一服務也可從詳細視窗右上角直接匯出。匯出包含顯示名稱、描述、分類、unit、scope、Port、Open URL 與最愛設定。遠端主機只匯出位址、SSH 使用者名稱與 SSH Port；不匯出主機顯示名稱、SSH 金鑰、known_hosts、指紋、密碼、session 或 journal。檔案仍可能包含內部 IP 與私有網址，應自行妥善保存。

Add service 頁右上角的 Import JSON 先顯示新增主機／服務與重複服務的預覽，再詢問是否覆蓋；可選「Overwrite & import」或「Import new only」。後端 API 預設跳過重複服務，不刪除未出現在檔案中的服務，也不啟動、停止或建立 systemd unit。遠端主機以儲存的 IP／hostname、SSH 使用者名稱和 SSH Port 比對；三者相同時沿用現有主機。缺少時新增未信任主機，顯示名稱設成 SSH 使用者名稱；若同 IP／hostname、同使用者已有其他 Port，名稱設成 `username (port)`。覆蓋內建服務時可更新別名、分類、描述、Open URL、Port 與最愛，Host／scope／unit 保持 catalog 定義；手動新增的服務可更新描述與分類。新服務直接註冊，不做即時 systemd 存在性檢查。新主機須在 Hosts 安裝公鑰並核對指紋後，相關服務才能正常查詢狀態與 Log。匯入檔上限 1 MiB、250 項服務；格式以 `format` 與 `version` 欄位辨識。

### 限時追蹤（藍色鈴鐺）

Services 詳情／編輯與 Open ports 個別項目視窗提供藍色鈴鐺，選擇 5、10、20 分鐘或 1 小時後，每 5 秒查詢該項目，再次點擊鈴鐺停止。Services 追蹤 systemd 狀態、已設定 Port 的 TCP 結果與最近 150 行 journal；手動 Port 僅追蹤 TCP，不將來源文字當作 unit。Services 來源的 Port 共用該服務的追蹤，不修改 Port 設定。查詢仍使用原有登入及 SSH／journal 權限。

追蹤由網頁執行，關閉網頁不繼續發出請求。瀏覽器 localStorage 僅保存項目 ID、類型及絕對到期時間，不保存 Log；使用同一瀏覽器重新開啟且登入後，未到期者恢復查詢，倒數不重設。逾時查詢會取消，上一輪未完成時不重疊查詢；瀏覽器背景分頁節流可能延遲五秒週期。登出停止查詢，但保留到期時間。到期／手動停止不會自動開啟 Log SSE，可按 Resume 恢復原有 Log 追蹤。

Tracking 與頂端 Live／Not live 獨立；已限時追蹤的項目不再重複執行三秒狀態輪詢。Overview 顯示剩餘時間、最近狀態和查詢錯誤；可從該處按鈴鐺停止。

## 密碼、JSON 一致性與串流限制

密碼政策共用 `app/static/password-policy.json`：1–256 Unicode code points，不 trim／截斷；拒絕 U+0000–001F、007F–009F 及 surrogate。安裝器（含保留既有密碼）、登入 API、前端共用此政策；既有不合規密碼需用 reset 更新，不能保持後繼續安裝。

所有執行時 JSON 使用 `app/storage.py` 的 reentrant thread lock 與 `.json.lock` flock。同一台 Linux 主機的多程序共用資料目錄時也互斥。單檔以 fsync + atomic replace 寫入；匯入與多欄位編輯先暫存，交易 commit 前將舊資料寫入 0600 的 `.json-transaction.json`。寫入失敗即 rollback；程序中斷後，下次讀取／啟動先完成回復，回復失敗會停止讀寫，不顯示半套資料。請使用本機支援 flock／fsync 的檔案系統，勿假設任意網路磁碟具有相同保證。

Session 每次從加鎖的儲存層確認，不使用跨請求的失效快取。SSE 每 5 秒重新驗證（無 Log 也檢查），撤銷／到期／斷線會終止本機 journalctl 或 SSH 程序，2 秒未結束則 kill。實際遠端 sshd 對斷線程序的處理仍受遠端系統配置影響。

匯入上限是 1 MiB（1,048,576 bytes）。前端預檢 file.size，再分塊累計讀取，送出前檢查 JSON 編碼後大小；後端先驗 Content-Length，再對 request.stream 每塊累計，超限回 413 並停止讀取，不依賴客戶端提供的長度。
