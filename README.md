# VideoVault：短影片收藏 SOP

```
手機 / 公司電腦 / 私人電腦                       私人電腦（本地）
┌───────────────────────┐   videos.json   ┌──────────────────────────────┐
│ 管理網站 (GitHub Pages) │ ─────────────▶ │ 本地下載站 (start.bat)        │
│ index.html             │ ◀───────────── │ 勾選 → 依平台自動分派下載      │
│ 貼網址 → 加入清單        │  標記「已下載」  │ FB→fdown  IG→saveclip         │
└───────────────────────┘                 │ Threads→threadsdownloader    │
                                          │ YouTube→Parabolic            │
                                          └──────────────────────────────┘
```

| 檔案 | 用途 |
|---|---|
| `index.html` | 管理網站（發佈到 GitHub Pages） |
| `videos.json` | 影片清單資料（由網站透過 GitHub API 讀寫） |
| `common.js` / `style.css` | 兩個網站共用 |
| `manifest.webmanifest` / `sw.js` / `icon.svg` | 讓手機可「加到主畫面」並出現在分享選單 |
| `local-downloader/` | 本地下載站（`start.bat` 啟動，需要 Python 3） |

## 一次性設定

### 1. 建立 GitHub 儲存庫並開啟 Pages
1. 在 GitHub 建立新的 repo（例如 `video-vault`），把本資料夾全部推上去。
2. repo → **Settings → Pages** → Source 選 `Deploy from a branch`，Branch 選 `main` / `(root)`。
3. 幾分鐘後網站位於 `https://<帳號>.github.io/video-vault/`。

> 免費帳號的 Pages 需要 public repo，也就是清單內容別人看得到（只有網址和備註）。
> 若介意，可以用 private repo + 私有 Pages（需 GitHub Pro），或乾脆不開 Pages、在各電腦用本機開啟 `index.html`。

### 2. 建立 Token（寫入用）
GitHub → Settings → Developer settings → **Fine-grained tokens** → Generate new token
- Repository access：**Only select repositories** → 選 `video-vault`
- Permissions → Repository permissions → **Contents：Read and write**

### 3. 在管理網站設定
開啟管理網站 → 右上「設定」→ 填入帳號、repo、Token、裝置名稱 → 儲存。
接著在「設定碼」區塊按「複製目前的設定碼」，傳給自己的其他裝置 / 本地下載站貼上即可。

### 4. 手機：加到主畫面
- **Android（Chrome）**：開啟管理網站 → 選單「安裝應用程式」。之後在 FB / IG / Threads / YouTube 按「分享」→ 選 **VideoVault**，網址會自動帶入。
- **iPhone（Safari）**：分享 →「加入主畫面」。iOS 不支援網頁出現在分享選單，請「複製連結」後開 VideoVault 按「貼上剪貼簿」。

### 5. 電腦：書籤小工具
設定 → 「電腦版書籤小工具」，把按鈕拖到書籤列；看影片時點一下就會帶著網址開啟管理網站。

### 6. 本地電腦：安裝「自動填入」擴充功能（Chrome / Edge）
網頁基於安全限制，無法直接把網址填進 fdown / saveclip / threadsdownloader 的輸入框，所以用一個小擴充功能來做。
1. 網址列輸入 `chrome://extensions`（Edge 為 `edge://extensions`）。
2. 開啟右上（Edge 在左下）的 **開發人員模式**。
3. 按 **載入未封裝項目**，選擇本專案的 `browser-extension` 資料夾。

之後本地下載站開啟下載網站時，網址會自動填好，下載鈕會閃爍，按一下即可。
（為了尊重網站的機器人驗證，擴充功能只填入、不代按下載。）

## 日常流程（SOP）
1. **看到想收藏的影片** → 分享 / 複製連結 → 在管理網站「加入清單」（可加備註）。
2. **回到私人電腦** → 點兩下 `local-downloader/start.bat`，瀏覽器會自動開啟本地下載站。
3. 勾選要下載的影片 → **下載所選**：
   - **yt-dlp 全自動**：背景下載到下載資料夾（依平台分子資料夾），完成後自動標記「已下載」。
   - **下載網站（FB / IG / Threads）**：自動開啟對應網站並填好網址（需安裝擴充功能，否則按 `Ctrl+V` 貼上）→ 按下載 → 回來按「✓ 完成，下一部」。
     網站不能用時按「✗ 這個不行，換 ○○」，會自動改開下一個來源。
   - **Parabolic（YouTube）**：自動開啟 Parabolic 並複製網址 → 在 Parabolic 按新增下載 → 回來按「完成」。
4. 已下載的影片在各裝置都會顯示「已下載・私人電腦」，不會重複下載或搞不清楚在哪台。

## 所有影片集中在一個地方
所有影片都放在 **`影片\VideoVault\<平台>\`**（本地下載站「設定」可改位置），右上「開啟資料夾」可直接打開。

| 下載方式 | 怎麼集中 |
|---|---|
| yt-dlp 全自動 | 直接存進 VideoVault |
| 下載網站（fdown、SaveClip…） | 按「✓ 完成」後，程式會到瀏覽器「下載」資料夾找出**開啟網站之後**新下載的影片，等下載完成再自動搬進 VideoVault（可在設定關閉） |
| Parabolic | Parabolic 的設定檔有加密，程式無法幫你改。請在 Parabolic 新增下載時，把「儲存資料夾」選為 `影片\VideoVault\youtube`，它會記住 |


## 下載來源管理
本地下載站右上角 **「下載來源」**：每個平台可以有多個來源（下載網站、Parabolic、yt-dlp 全自動）。

- **啟用 / 停用**：勾選框。預設已放入幾個驗證過可連線的備用站（SnapSave、FDownloader、FastDL、SSSInstagram、Threadster、SaveThr），預設停用。
- **新增網站**：填名稱與網址即可。輸入框 / 下載鈕的「選擇器」可留空，擴充功能會自動找網址輸入框。
  網址中可用 `{url}` 代入影片網址（適用支援網址參數的網站）。
- **自動排序（預設開啟）**：依「最近 20 次成功率」與「連線檢查」排序，第一名就是下載時使用的來源。
  - 成功率來自：按「完成」＝成功、按「換下一個來源」＝失敗、yt-dlp 的實際下載結果。
  - 連線檢查：程式啟動時自動檢查，也可按「重新檢查連線」。連不上的來源會被大幅降分。
  - 關閉自動排序時，依你用 ↑↓ 排的順序。
- yt-dlp 下載失敗時，下載卡片會出現「改用其他來源」，一鍵改用網站下載。

> 系統不會自動上網搜尋並加入新的下載站：這類網站常夾帶惡意廣告或假下載鈕，新站請自己確認可信後再加入。

IG 有時需要登入才能下載：設定 → 進階的「登入 cookies 來源瀏覽器」選 `firefox`（Chrome / Edge 在執行中時 cookies 檔會被鎖住，較容易失敗）。
更新擴充功能後，要到 `chrome://extensions` 對「VideoVault 自動填入」按一下重新載入 ⟳。

## 資料格式（`videos.json`）
```json
{
  "version": 1,
  "updatedAt": "2026-09-27T08:00:00.000Z",
  "videos": [
    {
      "id": "m1abc2def",
      "url": "https://www.instagram.com/reel/XXXX",
      "platform": "instagram",
      "note": "料理",
      "addedAt": "2026-09-27T07:00:00.000Z",
      "addedFrom": "手機",
      "status": "pending | downloaded",
      "downloadedAt": null,
      "downloadedOn": null,
      "file": null
    }
  ]
}
```
網址加入時會去掉追蹤參數（`igsh`、`fbclid`、`si`…），YouTube 的 `youtu.be` 統一轉成 `watch?v=`，以避免同一支影片重複收錄。
