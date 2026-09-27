// VideoVault 自動填入
// 本地下載站開啟下載網站時，網址後面會帶 #vv=<影片網址>&vvi=<輸入框選擇器>&vvb=<下載鈕選擇器>。
// 沒有 #vv= 的網頁，這支程式什麼都不做。
// 不會自動按下載（很多下載站有機器人驗證，留給使用者本人按）。
(() => {
  'use strict';
  // 同一分頁再次開啟時只有 # 後面改變，靠 hashchange 重新填入
  window.addEventListener('hashchange', start);
  if (/[#&]vv=/.test(location.hash)) start();

  function params() {
    const out = {};
    for (const part of location.hash.slice(1).split('&')) {
      const i = part.indexOf('=');
      if (i < 0) continue;
      try { out[part.slice(0, i)] = decodeURIComponent(part.slice(i + 1)); } catch {}
    }
    return out;
  }

  function query(sel) {
    if (!sel) return null;
    try { return document.querySelector(sel); } catch { return null; }
  }

  function visible(el) {
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden';
  }

  // 沒指定選擇器時，找最像「貼上網址」的輸入框
  function guessInput() {
    const fields = [...document.querySelectorAll('input[type=text], input[type=url], input[type=search], input:not([type]), textarea')]
      .filter(visible);
    const hint = /url|link|http|網址|連結|链接|paste|貼|粘/i;
    const text = el => [el.placeholder, el.name, el.id, el.getAttribute('aria-label'), el.className].join(' ');
    return fields.find(el => hint.test(text(el))) || fields[0] || null;
  }

  function guessButton(input) {
    const scope = input.closest('form') || input.parentElement?.parentElement || document;
    const buttons = [...scope.querySelectorAll('button, input[type=submit]')].filter(visible);
    const hint = /download|下載|下载|get|go|load|search|submit|start/i;
    const label = b => [b.textContent, b.value, b.id, b.className, b.type].join(' ');
    return buttons.find(b => !/paste|clear|貼上|粘贴|清除/i.test(label(b)) && hint.test(label(b)))
      || buttons.find(b => b.type === 'submit') || null;
  }

  function setValue(el, value) {
    // 用原生 setter，確保 React / Vue 類框架也收得到
    const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }

  function highlight(btn) {
    if (!btn) return;
    btn.scrollIntoView({ block: 'center', behavior: 'smooth' });
    btn.style.outline = '4px solid #ff7a3d';
    btn.style.outlineOffset = '3px';
    let on = true;
    const t = setInterval(() => { on = !on; btn.style.outlineColor = on ? '#ff7a3d' : 'transparent'; }, 600);
    btn.addEventListener('click', () => { clearInterval(t); btn.style.outline = ''; }, { once: true });
  }

  function start() {
    const p = params();
    const url = p.vv;
    if (!url) return;
    let tries = 0;
    const timer = setInterval(() => {
      tries++;
      const input = query(p.vvi) || guessInput();
      if (input) {
        if (input.value !== url) setValue(input, url);
        // 網頁載入後期可能清空輸入框，多確認幾次
        if (tries >= 6) {
          clearInterval(timer);
          input.focus();
          highlight(query(p.vvb) || guessButton(input));
          history.replaceState(null, '', location.pathname + location.search);
        }
      } else if (tries > 40) {
        clearInterval(timer);
      }
    }, 250);
  }
})();
