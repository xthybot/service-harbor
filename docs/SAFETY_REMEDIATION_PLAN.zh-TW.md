# 安全、資料一致性與生命週期修正計畫

日期：2026-10-04；基線 `5de6a2c`；工作分支 `fix/lifecycle-consistency`。

## 目標與界線

依本次使用者提供的八節審查清單完成實作、隔離故障回歸及文件更新。保留原生前端與 JSON 儲存架構、UI 風格、同源/session/SSH 安全界線。本次不修改授權文件、不推送、不部署、不讀正式秘密、不控制正式服務。不新增系統套件。只使用臨時 DATA_DIR、虛構資料與模擬 systemctl/sudo/SSH。

## 執行順序與分工

1. 主代理盤點現有文件、測試、程式與 Git；建立新分支。確認既有 License 已提交為基線。
2. 安裝生命週期工作：`scripts/lifecycle.py`、新增離線撤銷工具與 `tests/test_lifecycle.py`。以隔離故障注入驗證再修改；不碰共用 storage，必要介面由主代理整合。
3. 前端工作：`app/static/`、Node mock 測試；auth epoch / cancellation、統一視窗清理、drawer/log generation、busy/inventory、Hosts load queue、焦點管理。主代理保留 config-transfer.js 的預覽憑據整合。
4. Journal 工作：`app/systemd.py`、`tests/test_journal.py`。cursor 接續、身份失效與 subprocess 清理；主代理整合 main.py endpoint。
5. 主代理資料工作：`app/main.py`、`registry.py`、`config_transfer.py`、URL 驗證及隔離回歸。預覽 revision 與 document 綁定、短交易再確認、外部 probe 移出鎖、共用不變條件。
6. 統一文件、安全 sudoers 範例、所有既有及新增測試、語法、diff、提交內容審查。全部通過後本機 main 可安全快轉才合併。

## 逐項驗收清單

- [x] 二A 登出失敗不得宣稱撤銷；遮蔽並提供重試。
- [x] 二B auth epoch 清理 dialog/modal/drawer/confirm/import/inventory；取消請求、Live/Tracking/SSE；confirmation Promise 結束；保留 tracking 絕對到期。
- [x] 二C 登入401顯示錯密碼/限速；二D SSE去重退避session檢查，區分斷線與撤銷。
- [x] 三A 預覽無衝突不overwrite；覆蓋綁定預覽資料與版本；交易內核對；新衝突409再預覽；保留skip與不匯入信任。
- [x] 三B snapshot/probe/短交易；修改主機與服務後拒絕過時probe；慢probe不阻塞登入登出讀取。
- [x] 三C add/edit/settings/import同不變條件；external URL必填；export可import；URL authority/IDNA/IP/IPv6。
- [x] 四A 移除失敗可重試；ENV/receipt一致性；進度明確。
- [x] 四B ownership/legacy遷移、保護路徑/..、JSON檔案類型、混合ssh、安全暫存清理、symlink。
- [x] 四C recovery後共用storage撤銷，舊session不復活；備份/遷移說明。
- [x] 四D 停止前recovery preflight；rollback各階段獨立；不一致不重啟；記憶體快照非斷電整機回復。
- [x] 四E user manager/XDG unit位置、systemd directive編碼、特殊路徑早拒絕；venv/uv相容。
- [x] 五A Status/Recent成功與失敗generation；五B desiredFollow；五C身份變動與跨頁刪改。
- [x] 五D cursor銜接，不文字去重；缺口可見；權限/行數/子程序清理維持。
- [x] 六1–5 最愛by-ID、busy重算、inventory事件、Hosts刷新佇列、host改名位址觸發refresh。
- [x] 六6–9 export選項保留、ports空結果、頂層Escape/focus/Ctrl+K、Live/Log/Tracking分離。
- [x] 七1–8 sudoers先驗證才安裝、預設註解、原機/跨機復原、移除快取說明、Monitor另裝/註冊、不聲稱superpowers、模板走安裝器、Ubuntu/Python範圍。
- [x] 八 Python/Node全部回歸、語法/diff、提交檔案與秘密界線檢查；問題→修復→證據交付；分清隔離與真機未驗證。

## 驗證方法

Python 使用現有可用解譯器執行 `-m unittest discover -s tests -v`；程式 import 前設置 TemporaryDirectory DATA_DIR。前端用 `node --test tests/*.test.cjs`，控制延遲回應/Abort/EventSource並檢查實際UI狀態，不以文字搜尋取代動態驗證。安裝所有特權命令及刪除目標均模擬或隔離。Python compile、所有 JS `node --check`、shell `bash -n`、`git diff --check`。結果與未驗證項目記於驗收文件；此計畫的勾選依最終證據更新。
