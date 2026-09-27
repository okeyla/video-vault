// 讀取網址中的 #vv=<影片網址>，填進下載網站的輸入框。不會自動按下載（網站有機器人驗證，留給使用者本人按）。
(() => {
  'use strict';
  const SITES = [
    { host: /(^|\.)fdown\.net$/,              input: '#downloadinput', button: '#downloadbtn' },
    { host: /(^|\.)saveclip\.app$/,           input: '#s_input',       button: '#search-form button' },
    { host: /(^|\.)threadsdownloader\.com$/,  input: '#postUrl',       button: '#loadVideos' },
  ];
  const site = SITES.find(s => s.host.test(location.hostname));
  if (!site) return;

  function readUrl() {
    const m = location.hash.match(/[#&]vv=([^&]+)/);
    if (!m) return null;
    try { return decodeURIComponent(m[1]); } catch { return null; }
  }

  function setValue(el, value) {
    // 用原生 setter，確保 React / Vue 類框架也收得到
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
    setter.call(el, value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }

  function highlight(btn) {
    if (!btn) return;
    btn.scrollIntoView({ block: 'center', behavior: 'smooth' });
    btn.style.outline = '4px solid #ff7a3d';
    btn.style.outlineOffset = '3px';
    btn.style.transition = 'outline-color .6s';
    let on = true;
    const t = setInterval(() => { on = !on; btn.style.outlineColor = on ? '#ff7a3d' : 'transparent'; }, 600);
    btn.addEventListener('click', () => { clearInterval(t); btn.style.outline = ''; }, { once: true });
  }

  function fill() {
    const url = readUrl();
    if (!url) return;
    let tries = 0;
    const timer = setInterval(() => {
      const input = document.querySelector(site.input);
      tries++;
      if (input) {
        if (input.value !== url) setValue(input, url);
        // 網頁載入後期可能清空輸入框，多確認幾次
        if (tries >= 6) {
          clearInterval(timer);
          input.focus();
          highlight(document.querySelector(site.button));
          history.replaceState(null, '', location.pathname + location.search);
        }
      } else if (tries > 40) {
        clearInterval(timer);
      }
    }, 250);
  }

  fill();
  window.addEventListener('hashchange', fill);
})();
