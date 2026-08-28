# Mai Beeper Adapter

讓 MaiBot 透過 **Beeper Desktop API** 收發訊息的簡單連接插件。

目前支援：

- 私聊與群聊文字收發
- 圖片收發
- 聊天白名單
- 依聊天室名稱自動尋找 Chat ID
- 傳送配對文字，自動綁定聊天室
- 自動重連、定時補漏、訊息去重
- Beeper WebSocket 暫時失效時改用 REST API 繼續收訊

語音、影片與一般檔案目前會顯示成文字提示，不會傳送檔案本身。

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
git clone https://github.com/sunfish1728/MaiBot-Beeper-Adapter.git mai-beeper-adapter
```

### 方法三：ZIP

將發布的 `Mai-Beeper-Adapter-0.2.2.zip` 解壓縮，再把裡面的同名資料夾放進 MaiBot 的 `plugins` 目錄。

## 第一次設定

1. 在插件設定中填入剛才建立的 **Access Token**。
2. 到「自動取得聊天室」選擇其中一種方法：
   - **依名稱自動尋找**：填入 Beeper 畫面上的完整聊天室名稱。只有唯一且名稱完全相同時才會採用。
   - **訊息配對**：開啟「啟用訊息配對」，把配對文字改成自己容易辨識的內容，例如 `#MaiBot配對5827`。
3. 開啟插件並儲存。
4. 如果使用訊息配對，等插件連線後，到目標 Beeper 聊天傳送一次完全相同的配對文字。
5. 日誌出現「Beeper 訊息配對成功」後，該聊天室便會自動開始使用。
6. 配對完成後可以關閉「啟用訊息配對」；已保存的聊天室仍然有效，也能減少不必要的聊天室清單掃描。

進階使用者仍可直接把 `chatID` 填入「聊天白名單」。三種來源可以同時使用。

沒有選到任何聊天室時，插件不會把 Beeper 訊息傳給 MaiBot。新增或配對聊天後會從當下開始監聽，不會把以前的聊天紀錄全部讀一遍。

訊息配對只接受完整相同、而且是啟用配對後新出現的最新訊息。已配對的正式 Chat ID 保存在插件自己的資料目錄，重新啟動 MaiBot 後仍然有效。

若要解除配對，重新開啟「啟用訊息配對」，儲存並等插件連線後，在該聊天室傳送設定頁顯示的「取消配對文字」。這只會移除自動保存的配對，不影響手動白名單或名稱設定。

## 測試是否成功

在白名單聊天中：

1. 傳送一段普通文字，確認 MaiBot 能看到並回覆。
2. 傳送一張圖片，確認 MaiBot 能讀到圖片。
3. 關閉 Beeper Desktop 約半分鐘後重新開啟，確認插件會自行恢復。

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

確認聊天室名稱沒有同名結果；若有同名，請使用「訊息配對」。也可以確認完整 `chatID` 已加入白名單。

### WebSocket 中斷

這不一定是故障。插件仍會用 REST API 定時補抓訊息，並在背景自動重新連接即時通知。

## 資料保存

插件只在 MaiBot 的專屬資料目錄保存各聊天的同步游標與已配對 Chat ID，用來避免重複、漏訊及保留配對結果；不會另外複製完整聊天記錄。Access Token 由 MaiBot 的插件設定管理。

## 參考文檔

- [MaiBot 插件開發指南](https://docs.mai-mai.org/plugin/)
- [MaiBot MessageGateway SDK 指南](https://github.com/Mai-with-u/maibot-plugin-sdk/blob/main/docs/guide.md)
- [Beeper Desktop API](https://developers.beeper.com/desktop-api/)
- [Beeper API 認證](https://developers.beeper.com/desktop-api/authentication/)

## License

MIT
