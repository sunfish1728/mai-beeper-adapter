# Mai Beeper Adapter

讓 MaiBot 透過 **Beeper Desktop API** 收發訊息的簡單連接插件。

目前支援：

- 私聊與群聊文字收發
- 圖片收發
- 語音收發（包含 GPT-SoVITS 等插件產生的 Base64 語音）
- 聊天白名單
- 依聊天室名稱自動尋找 Chat ID
- 傳送配對文字，自動綁定聊天室
- 自動重連、定時補漏、訊息去重
- Beeper WebSocket 暫時失效時改用 REST API 繼續收訊

影片與一般檔案目前會顯示成文字提示，不會傳送檔案本身。Beeper 接收的語音會保留原始音訊交給 MaiBot；實際能否辨識內容，取決於 MaiBot 已安裝的語音辨識功能。

## 使用前準備

1. 安裝並登入 [Beeper Desktop](https://www.beeper.com/download)。
2. 保持 Beeper Desktop 開啟。
3. 在 Beeper Desktop 打開 **Settings → Integrations**。
4. 啟用 Desktop API，按「Approved connections」旁邊的 `+` 建立 Access Token。

Token 等同於操作你 Beeper 聊天的鑰匙，請不要貼到公開場合。

## 安裝到 MaiBot OK

### 方法一：自動安裝（建議）

1. 解壓縮安裝包。
2. 雙擊 `install.cmd`。
3. 看到「安裝成功」後，重新開啟 MaiBot OneKey。

安裝器會自動尋找 MaiBot OneKey 實際使用的 `plugins` 資料夾。更新插件時，原本的 `config.toml` 設定會保留。

### 方法二：手動複製

1. 在 MaiBot OK 按 `Ctrl + L` 打開 MaiBot 根目錄。
2. 進入 `plugins` 資料夾。
3. 將整個 `Mai-Beeper-Adapter` 資料夾放進去。
4. 回到 MaiBot WebUI 的「插件管理」，找到 **Mai Beeper Adapter**。

安裝後不需要另外執行 `pip install`。

也可以在 MaiBot 的 `plugins` 資料夾使用 Git 安裝：

```text
git clone https://github.com/sunfish1728/mai-beeper-adapter.git mai-beeper-adapter
```

### 方法三：ZIP

將發布的 `Mai-Beeper-Adapter-0.4.3.zip` 解壓縮，再把裡面的同名資料夾放進 MaiBot 的 `plugins` 目錄。

## 第一次設定

1. 在插件設定中填入剛才建立的 **Access Token**。
2. 在 **Beeper 聊天白名單** 新增 Beeper 畫面上顯示的完整聊天室名稱。
3. 把 **配對文字** 改成自己容易辨識的內容，例如 `#MaiBot配對5827`。
4. 開啟插件並儲存。
5. 到剛才填寫的同名 Beeper 聊天室，傳送一次完整相同的配對文字。
6. 日誌出現「Beeper 聊天配對成功」後，插件會自動保存 Beeper ID 並從當下開始監聽。

聊天室名稱只是配對白名單，不會只靠名稱自動猜測聊天室。即使有同名聊天，也只有實際送出配對文字的那一個會連結。

若要停止某個聊天室，直接從 **Beeper 聊天白名單** 刪除它的名稱並儲存。插件會同步刪除保存的 Beeper ID、同步游標與監聽狀態，不需要另外傳送取消配對文字。

沒有已配對的聊天室時，插件不會把 Beeper 訊息傳給 MaiBot。新增並配對後會從當下開始監聽，不會重播以前的聊天紀錄。

## 測試是否成功

在白名單聊天中：

1. 傳送一段普通文字，確認 MaiBot 能看到並回覆。
2. 傳送一張圖片，確認 MaiBot 能讀到圖片。
3. 傳送一段語音，確認 MaiBot 能收到；再讓語音插件產生一段語音，確認 Beeper 聊天中出現可播放的音訊。
4. 關閉 Beeper Desktop 約半分鐘後重新開啟，確認插件會自行恢復。

群聊中要不要主動回覆、多久回一次，仍由 MaiBot 自己的聊天策略決定。

## 常見問題

### 顯示「無法連線 Beeper Desktop」

確認 Beeper Desktop 已經開啟，而且 API 地址保持預設的：

```text
http://127.0.0.1:23373
```

### 顯示「Access Token 無效」

回到 Beeper Desktop 的 **Settings → Integrations**，重新建立 Token，完整複製到插件設定。

### 日誌有連線成功，但聊天沒有反應

確認白名單中的聊天室名稱與 Beeper 畫面完全相同，並在該聊天室重新傳送一次設定頁顯示的完整配對文字。名稱新增後，先前就存在的舊配對文字不會被採用。

### 收得到圖片，但 MaiBot 看不懂內容

插件會把完整圖片資料交給 MaiBot。請另外確認 `model_config.toml` 的 `model_task_config.vlm.model_list` 不是空白，且所選模型的 `visual` 為 `true`；沒有設定視覺模型時，MaiBot 不會呼叫 VLM，日誌中的 `visual_refresh` 會保持 0。

### WebSocket 中斷

這不一定是故障。插件仍會用 REST API 定時補抓訊息，並在背景自動重新連接即時通知。

## 資料保存

插件只在 MaiBot 的專屬資料目錄保存「聊天室名稱 → Beeper ID」的配對結果與同步游標，用來避免重複或漏訊；不會另外複製完整聊天記錄。從白名單刪除名稱時，對應的 ID 與游標也會刪除。Access Token 由 MaiBot 的插件設定管理。

## 參考文檔

- [MaiBot 插件開發指南](https://docs.mai-mai.org/plugin/)
- [MaiBot MessageGateway SDK 指南](https://github.com/Mai-with-u/maibot-plugin-sdk/blob/main/docs/guide.md)
- [Beeper Desktop API](https://developers.beeper.com/desktop-api/)
- [Beeper API 認證](https://developers.beeper.com/desktop-api/authentication/)

## License

MIT
