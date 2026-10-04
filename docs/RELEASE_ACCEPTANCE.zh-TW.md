# Service Harbor 分享版本驗收

日期：2026-10-04。測試使用臨時 DATA_DIR、虛構服務及獨立 loopback HTTP 伺服器；不使用正式密碼／SSH key，不控制正式被管理的服務。

## 任務結果

| Task | 修改 | 驗收證據 |
| --- | --- | --- |
| T1 | 預設只有 Dashboard；其他服務為私密 local-catalog 或手動／JSON 匯入 | 空資料 catalog／HTTP export 均只有自身；範例檔使用 example-web.service；追蹤檔無原主機自訂 service ID |
| T2 | 安裝/API/前端共用 password-policy.json | 0／1／256／257 字元、256 emoji、控制字元、surrogate；安裝超限後重新提示；HTTP 422 |
| T3 | README 頂部說明 HTTP 明文與可信任私人網路範圍 | 文件審查；安裝器不聲稱提供 TLS |
| T4 | 所有 runtime JSON 共用 RLock/flock；匯入／複合編輯交易 | 100 個執行緒更新、4 程序共 32 筆、30 組別名／最愛／URL／Port 並行；7 個匯入檔逐個注入失敗均全部復原；寫入中程序中斷後重讀復原 |
| T5 | 五秒 session 複查及 subprocess cleanup | 靜默／持續輸出、logout、session 到期、檔案撤銷、disconnect、cancel、ASGI AnyIO cancellation scope；忽略 TERM 的模擬程序兩秒後 KILL |
| T6 | 前後端串流累計 1 MiB | 恰好上限通過、超限不再讀第三塊、Content-Length 超限不讀 body、偽造較小長度仍 413；前端取消 reader，JSON 序列化後超限拒絕 |
| T7 | 整合及部署 | 隔離 HTTP 匯入／preview／編輯／export；正式 Dashboard 重啟後 active/running、NRestarts=0，登入可讀取既有清單；公開副本另跑相同驗收 |

## 可重跑指令

```bash
.venv/bin/python -m unittest discover -s tests -v
node --test tests/frontend-limits.test.cjs
for file in app/static/*.js; do node --check "$file"; done
for file in scripts/*.sh; do bash -n "$file"; done
git diff --check
```

本次 24 項 Python 測試、3 項 Node 測試通過。Node 僅驗收使用，不是部署依賴。HTTP 測試啟動獨立 uvicorn，使用臨時 socket／資料並自動關閉。SSH 情境驗證的是相同串流管理函式對模擬子程序的終止，不會真的 SSH 到他人主機。

## 發布邊界

公開 repository `service-harbor` 從乾淨檔案快照建立獨立 root commit，沒有私人 Git 歷史。排除 data/、.venv、環境檔、.git、SSH keys、備份和 docs/superpowers 歷史規劃。原私人維運 repository 保留歷史，命名加上 -private；不可直接將其分支推往公開 remote。

## 尚未驗證／實作界線

- 未執行實體主機重新開機、完整重新安裝或移除，未連線真實遠端 SSH 驗證 sshd 的斷線清理政策。
- 保證在本機 Linux 支援 flock/fsync 的檔案系統；未驗證 NFS、停電硬體故障與損壞檔案系統。
- crash 復原由模擬程序寫入中直接退出驗證；無法恢復已損毀的儲存媒體。
- 五秒是正常事件迴圈及儲存系統可用時的檢查週期；程序排程或磁碟阻塞仍可能延後。
- 此次不提供 HTTPS、憑證管理或公網部署；僅適合可信任私人網路。
