# 裝置監控整合

裝置收集器和專用網頁位於獨立專案 `~/host-device-monitor`。本 repository 的乾淨預設只含 Dashboard 自身；`host-device-monitor.service` 須先在另一專案安裝，再透過 Add service 註冊。公開 sudoers 範本不預先授權任何真實單元；詳細監控範圍、權限、安裝、查詢及移除指令以該專案的 `README.md` 與 `docs/COLLECTOR.md` 為準。

檢視器網址為 `http://<LAN-IP>:8766/`。原 Dashboard 的 `/#monitor` 書籤會導向該網站；導覽選單和監控檢視頁已移除。此連結不表示獨立專案已安裝。

另外安裝並在 Dashboard 註冊後，Services 才會出現 **Host Device Monitor** 卡片；有權讀取 journal 時可看日誌，Start／Stop／Restart 仍需管理員對真實 unit 設定精確 sudoers。Dashboard 和獨立網站都以一般使用者執行；系統層收集器才需要 `input` 裝置讀取權限。

收集器只記錄輸入裝置接拔、KEY_POWER 事件與 HDMI／DP 連線狀態到 system journal；不記錄一般按鍵、滑鼠點擊或座標，不擷取畫面，也不更改電源鍵行為。獨立網站顯示目前 I/O 狀態及監控事件。Dashboard 的 Services 只顯示收集器本身的 systemd 狀態和 journal，沒有裝置事件專頁。

查看已安裝單元與最近日誌：

```bash
systemctl status host-device-monitor.service --no-pager
journalctl -u host-device-monitor.service -n 50 --no-pager -o short-iso
systemctl --user status host-device-monitor-web.service --no-pager
```

更新收集器原始碼後，必須從新專案執行 `sudo ./scripts/install-collector.sh` 才會更新 `/usr/local/lib/host-device-monitor/host_device_monitor.py`。只修改網頁時，執行 `systemctl --user restart host-device-monitor-web.service`。
