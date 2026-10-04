# 分享版本修正與驗收

本次只在隔離資料目錄測試，不操作正式服務的 start/stop，也不公開 repository 或改寫 Git 歷史。

- [x] T1 公開預設與本機設定分離：空資料只顯示 Dashboard；原主機清單移至 gitignored local-catalog.json、保留 ID／權限；追蹤檔無主機專用服務名稱。提供純範例匯入 JSON。
- [x] T2 密碼一致：1–256 個 Unicode code points，禁止控制字元與 surrogate；安裝/API/前端同規格，不自動截斷或 trim；測試 0/1/256/257、emoji、換行、既有密碼。
- [x] T3 README 明確 HTTP 未加密，僅可信任私人網路，不適合公開網路／公共 Wi-Fi；不聲稱登入密碼能替代 TLS。
- [x] T4 統一 JSON 讀改寫鎖：thread RLock + process flock；測試多執行緒／多程序不同項目更新無遺失。匯入和複合編輯用交易，注入每個檔案寫入錯誤驗證全部還原；崩潰後下次讀取先復原，不回傳半套資料。
- [x] T5 SSE 每 5 秒重新驗證 session（靜默串流也適用），失效終止 local journal／SSH 子程序、必要時 kill；測試撤銷／到期／disconnect／有輸出與無輸出。
- [x] T6 1 MiB：後端 Content-Length 預檢及 request.stream 累計，超限立刻 413；前端 file.size、分塊累計、序列化後 byte count；驗證邊界、缺少／偽造 Content-Length，且超限不再讀下一塊、不送出匯入。
- [x] T7 全項回歸、語法檢查、文件同步、正式服務重啟與唯讀驗收，合併 main；公開 repository 使用 service-harbor、原 private repo 改名加上 -private；發布採無歷史乾淨快照，完成後核對遠端 SHA。

驗收：`.venv/bin/python -m unittest discover -s tests -v`；前端限制以 `node --test tests/frontend-limits.test.cjs`；`node --check`、`bash -n`、`git diff --check`。測試必須將 DATA_DIR 設為 TemporaryDirectory，禁止使用真實密碼、cookie、主機資料或 SSH 連線。結果另列於 docs/RELEASE_ACCEPTANCE.zh-TW.md。

## 安全與一致性修正（2026-10-04）

本節以 `fix/lifecycle-consistency` 分支為工作基線；逐項證據與限制見 [安全修正驗收紀錄](docs/SAFETY_REMEDIATION_ACCEPTANCE.zh-TW.md)。本次只修改原始碼、隔離測試及文件；不部署正式服務、不推送 GitHub、不更改 LICENSE。

- [x] S1 登出失敗、401、跨登入世代、SSE session 重查及完整 UI 清理。
- [x] S2 匯入預覽憑據、交易內版本驗證、保留跳過衝突；外部 probe 移出全域鎖。
- [x] S3 新增／編輯／settings／匯入共用服務欄位不變條件與 HTTP URL authority 驗證。
- [x] S4 安裝／移除 ownership、重試、離線 session 撤銷、回復及 user manager 路徑防護。
- [x] S5 Status／Recent／SSE 以 generation、服務身分與 journal cursor 管理競態與續傳。
- [x] S6 Favorite、busy、inventory、Hosts 刷新佇列、Open ports 空結果、頂層 modal focus/Escape。
- [x] S7 sudoers 範本預設不授權、候選先 visudo 驗證、原機／跨主機操作與測試範圍文件同步。
- [x] S8 最終審核：全量隔離測試、語法／diff、敏感資料檢查、提交並安全合併本機 main。提交與合併資訊見驗收紀錄。
