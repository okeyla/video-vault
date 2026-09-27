// 最小 service worker：讓手機可「安裝到主畫面」並出現在分享選單。不做快取，資料永遠即時讀 GitHub。
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', () => {});
