/* VideoVault 共用邏輯：平台判斷、網址整理、GitHub 儲存、設定 */
(function (global) {
  'use strict';

  const PLATFORMS = {
    facebook:  { name: 'Facebook',  short: 'FB',   hosts: ['facebook.com', 'fb.watch', 'fb.com'],   site: 'https://fdown.net/' },
    instagram: { name: 'Instagram', short: 'IG',   hosts: ['instagram.com', 'instagr.am'],          site: 'https://saveclip.app/zh-tw9' },
    threads:   { name: 'Threads',   short: 'TH',   hosts: ['threads.net', 'threads.com'],           site: 'https://www.threadsdownloader.com/' },
    youtube:   { name: 'YouTube',   short: 'YT',   hosts: ['youtube.com', 'youtu.be'],              site: 'https://www.youtube.com/' },
    other:     { name: '其他',       short: '?',    hosts: [],                                       site: '' },
  };

  function hostMatches(host, domain) {
    return host === domain || host.endsWith('.' + domain);
  }

  function detectPlatform(url) {
    let host;
    try { host = new URL(url).hostname.toLowerCase(); } catch { return 'other'; }
    for (const [key, p] of Object.entries(PLATFORMS)) {
      if (p.hosts.some(d => hostMatches(host, d))) return key;
    }
    return 'other';
  }

  // 分享文字常夾帶說明，從中抽出所有網址
  function extractUrls(text) {
    const found = String(text || '').match(/https?:\/\/[^\s<>"'，。、）)]+/gi) || [];
    return [...new Set(found.map(u => u.replace(/[.,;!?]+$/, '')))];
  }

  // 去掉追蹤參數，讓同一支影片不會因分享來源不同而重複
  const TRACKING = /^(utm_.*|fbclid|igsh|igshid|mibextid|rdid|share_url|sfnsn|si|feature|xmt|slof|app)$/i;
  function normalizeUrl(raw) {
    let u;
    try { u = new URL(raw.trim()); } catch { return raw.trim(); }
    u.hash = '';
    for (const k of [...u.searchParams.keys()]) if (TRACKING.test(k)) u.searchParams.delete(k);
    const platform = detectPlatform(u.href);
    if (platform === 'youtube') {
      // youtu.be/ID、/shorts/ID 統一成 watch?v=ID
      let id = null;
      if (hostMatches(u.hostname, 'youtu.be')) id = u.pathname.slice(1).split('/')[0];
      const m = u.pathname.match(/^\/(shorts|live|embed)\/([\w-]{6,})/);
      if (m) id = m[2];
      if (id) return 'https://www.youtube.com/' + (m && m[1] === 'shorts' ? 'shorts/' + id : 'watch?v=' + id);
      u.hostname = 'www.youtube.com';
    }
    if (platform === 'instagram' || platform === 'threads') u.search = '';
    let s = u.href;
    if (s.endsWith('/') && u.pathname !== '/') s = s.slice(0, -1);
    return s;
  }

  function uid() {
    return Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
  }

  // ---------- UTF-8 base64 ----------
  function b64encode(str) {
    const bytes = new TextEncoder().encode(str);
    let bin = '';
    for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    return btoa(bin);
  }
  function b64decode(b64) {
    const bin = atob(b64.replace(/\s/g, ''));
    const bytes = Uint8Array.from(bin, c => c.charCodeAt(0));
    return new TextDecoder().decode(bytes);
  }

  // ---------- 設定 ----------
  const CFG_KEY = 'videovault.config';
  const DEFAULT_CFG = { owner: '', repo: '', branch: 'main', path: 'videos.json', token: '', device: '' };

  function loadConfig() {
    let saved = {};
    try { saved = JSON.parse(localStorage.getItem(CFG_KEY) || '{}'); } catch {}
    const cfg = { ...DEFAULT_CFG, ...saved };
    // 在 <owner>.github.io/<repo>/ 上開啟時，自動帶入帳號與儲存庫
    const m = location.hostname.match(/^([\w-]+)\.github\.io$/i);
    const repo = location.pathname.split('/')[1];
    if (m && repo && !cfg.owner && !cfg.repo) Object.assign(cfg, { owner: m[1], repo });
    return cfg;
  }
  function saveConfig(cfg) {
    try { localStorage.setItem(CFG_KEY, JSON.stringify(cfg)); } catch {}
  }
  // 設定碼：讓手機 / 公司電腦 / 本地下載站快速套用同一組設定
  function exportConfigCode(cfg) {
    const { owner, repo, branch, path, token } = cfg;
    return 'VV1.' + b64encode(JSON.stringify({ owner, repo, branch, path, token }));
  }
  function importConfigCode(code) {
    const s = String(code || '').trim();
    if (!s.startsWith('VV1.')) throw new Error('設定碼格式不正確');
    return JSON.parse(b64decode(s.slice(4)));
  }

  // ---------- GitHub 儲存 ----------
  class GitHubStore {
    constructor(cfg) {
      this.cfg = cfg;
      this.sha = null;
    }
    get ready() { return !!(this.cfg.owner && this.cfg.repo && this.cfg.path); }
    get canWrite() { return this.ready && !!this.cfg.token; }

    apiUrl() {
      const { owner, repo, path } = this.cfg;
      const p = path.split('/').map(encodeURIComponent).join('/');
      return `https://api.github.com/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/contents/${p}`;
    }
    headers() {
      const h = { Accept: 'application/vnd.github+json' };
      if (this.cfg.token) h.Authorization = 'Bearer ' + this.cfg.token;
      return h;
    }

    async load() {
      if (!this.ready) throw new Error('尚未設定 GitHub 儲存庫');
      const url = this.apiUrl() + '?ref=' + encodeURIComponent(this.cfg.branch || 'main') + '&_=' + Date.now();
      const res = await fetch(url, { headers: this.headers(), cache: 'no-store' });
      if (res.status === 404) { this.sha = null; return emptyData(); }
      if (!res.ok) throw new Error(await ghError(res));
      const json = await res.json();
      this.sha = json.sha;
      let content = json.content;
      if (!content && json.download_url) content = b64encode(await (await fetch(json.download_url, { cache: 'no-store' })).text());
      return normalizeData(JSON.parse(b64decode(content || '') || '{}'));
    }

    async put(data, message) {
      const body = {
        message,
        content: b64encode(JSON.stringify(data, null, 2) + '\n'),
        branch: this.cfg.branch || 'main',
      };
      if (this.sha) body.sha = this.sha;
      const res = await fetch(this.apiUrl(), { method: 'PUT', headers: { ...this.headers(), 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      if (!res.ok) { const err = new Error(await ghError(res)); err.status = res.status; throw err; }
      this.sha = (await res.json()).content.sha;
    }

    // 讀取最新 → 套用修改 → 寫回；多台裝置同時改時自動重試，不會覆蓋別人的變更
    async update(mutator, message) {
      if (!this.canWrite) throw new Error('需要 GitHub Token 才能寫入');
      for (let attempt = 0; attempt < 4; attempt++) {
        const data = await this.load();
        const result = mutator(data);
        if (result === false) return data;
        data.updatedAt = new Date().toISOString();
        try {
          await this.put(data, message);
          return data;
        } catch (e) {
          if ((e.status === 409 || e.status === 422) && attempt < 3) continue;
          throw e;
        }
      }
    }
  }

  function emptyData() { return { version: 1, updatedAt: null, videos: [] }; }
  function normalizeData(d) {
    const out = { ...emptyData(), ...d };
    out.videos = Array.isArray(out.videos) ? out.videos : [];
    return out;
  }
  async function ghError(res) {
    let msg = '';
    try { msg = (await res.json()).message || ''; } catch {}
    const hints = { 401: 'Token 無效或已過期', 403: '權限不足或 API 次數超過上限', 404: '找不到儲存庫（名稱錯誤，或私人庫未提供 Token）' };
    return `GitHub ${res.status}：${hints[res.status] || msg || res.statusText}`;
  }

  // ---------- 小工具 ----------
  function escapeHtml(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }
  function fmtDate(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    const pad = n => String(n).padStart(2, '0');
    return `${d.getFullYear()}/${pad(d.getMonth() + 1)}/${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }
  function guessDevice() {
    const ua = navigator.userAgent;
    if (/iPhone|Android.+Mobile/i.test(ua)) return '手機';
    if (/iPad|Android/i.test(ua)) return '平板';
    return '電腦';
  }

  global.VV = {
    PLATFORMS, detectPlatform, extractUrls, normalizeUrl, uid,
    loadConfig, saveConfig, exportConfigCode, importConfigCode,
    GitHubStore, escapeHtml, fmtDate, guessDevice,
  };
})(window);
