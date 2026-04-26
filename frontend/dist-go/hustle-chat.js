/**
 * Hustle AI Chat Widget — standalone, zero-dependency.
 * Usage: <script src="/hustle-chat.js" data-site="admin"></script>
 */
(function () {
  const SCRIPT = document.currentScript;
  const SITE = (SCRIPT && SCRIPT.getAttribute('data-site')) || 'auto';
  const API_BASE = '/api/v1/agent';
  let open = false, sending = false, remaining = 20, loaded = false;
  let messages = [];

  function getToken() {
    return localStorage.getItem('admin_token') || localStorage.getItem('access_token') || '';
  }

  function authHeaders() {
    return { 'Authorization': 'Bearer ' + getToken(), 'Content-Type': 'application/json' };
  }

  // ── Styles ──
  const style = document.createElement('style');
  style.textContent = `
    #hustle-chat-btn{position:fixed;bottom:24px;right:24px;z-index:9999;width:48px;height:48px;border-radius:50%;background:#f0b90b;color:#1e2329;border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;box-shadow:0 2px 8px rgba(0,0,0,.3);transition:background .2s}
    #hustle-chat-btn:hover{background:#f5d245}
    #hustle-chat-btn svg{width:24px;height:24px}
    #hustle-chat-panel{position:fixed;bottom:24px;right:24px;z-index:9999;width:400px;height:520px;background:#181a20;border:1px solid #2b3139;border-radius:12px;display:none;flex-direction:column;overflow:hidden;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
    #hustle-chat-panel.open{display:flex}
    .hc-header{display:flex;align-items:center;justify-content:space-between;padding:12px 16px;border-bottom:1px solid #2b3139;background:#1e2329}
    .hc-header-left{display:flex;align-items:center;gap:8px}
    .hc-logo{width:28px;height:28px;border-radius:6px;background:#f0b90b;display:flex;align-items:center;justify-content:center;color:#1e2329;font-weight:700;font-size:12px}
    .hc-title{font-weight:600;font-size:14px;color:#eaecef}
    .hc-badge{font-size:10px;padding:2px 6px;background:#181a20;border-radius:4px;color:#848e9c}
    .hc-remaining{font-size:10px;color:#848e9c}
    .hc-close{background:none;border:none;color:#848e9c;font-size:20px;cursor:pointer;line-height:1;padding:0 4px}
    .hc-close:hover{color:#eaecef}
    .hc-msgs{flex:1;overflow-y:auto;padding:12px 16px;display:flex;flex-direction:column;gap:10px}
    .hc-empty{text-align:center;color:#848e9c;font-size:12px;padding:32px 0}
    .hc-msg{display:flex}.hc-msg.user{justify-content:flex-end}.hc-msg.assistant{justify-content:flex-start}
    .hc-bubble{max-width:85%;padding:8px 12px;border-radius:8px;font-size:12px;line-height:1.6;white-space:pre-wrap;word-break:break-word}
    .hc-msg.user .hc-bubble{background:rgba(240,185,11,.15);color:#eaecef;border:1px solid rgba(240,185,11,.3)}
    .hc-msg.assistant .hc-bubble{background:#1e2329;color:#eaecef;border:1px solid #2b3139}
    .hc-cursor{display:inline-block;width:6px;height:14px;background:rgba(240,185,11,.6);margin-left:2px;vertical-align:middle;animation:hcBlink 1s infinite}
    @keyframes hcBlink{0%,100%{opacity:1}50%{opacity:0}}
    .hc-input-area{padding:12px 16px;border-top:1px solid #2b3139;background:#1e2329;display:flex;gap:8px}
    .hc-input{flex:1;background:#181a20;border:1px solid #2b3139;border-radius:8px;padding:8px 12px;font-size:12px;color:#eaecef;outline:none}
    .hc-input:focus{border-color:#f0b90b}
    .hc-input::placeholder{color:#848e9c}
    .hc-send{padding:8px 16px;background:#f0b90b;color:#1e2329;border:none;border-radius:8px;font-size:12px;font-weight:600;cursor:pointer;white-space:nowrap}
    .hc-send:hover{background:#f5d245}
    .hc-send:disabled{opacity:.4;cursor:default}
  `;
  document.head.appendChild(style);

  // ── DOM ──
  const btn = document.createElement('button');
  btn.id = 'hustle-chat-btn';
  btn.title = 'Hustle AI 助手';
  btn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z"/></svg>';

  const panel = document.createElement('div');
  panel.id = 'hustle-chat-panel';
  panel.innerHTML = `
    <div class="hc-header">
      <div class="hc-header-left">
        <div class="hc-logo">H</div>
        <span class="hc-title">Hustle</span>
        <span class="hc-badge">AI 助手</span>
      </div>
      <div style="display:flex;align-items:center;gap:8px">
        <span class="hc-remaining" id="hc-remain"></span>
        <button class="hc-close" id="hc-close">&times;</button>
      </div>
    </div>
    <div class="hc-msgs" id="hc-msgs"></div>
    <div class="hc-input-area">
      <input class="hc-input" id="hc-input" placeholder="输入问题…">
      <button class="hc-send" id="hc-send">发送</button>
    </div>
  `;

  document.body.appendChild(btn);
  document.body.appendChild(panel);

  const msgsEl = document.getElementById('hc-msgs');
  const inputEl = document.getElementById('hc-input');
  const sendBtn = document.getElementById('hc-send');
  const remainEl = document.getElementById('hc-remain');

  function updateRemaining() { remainEl.textContent = remaining + '/20'; }
  updateRemaining();

  function scrollBottom() {
    requestAnimationFrame(() => { msgsEl.scrollTop = msgsEl.scrollHeight; });
  }

  function renderMessages() {
    if (!messages.length) {
      msgsEl.innerHTML = '<div class="hc-empty">你好！我是 Hustle，AI 助手。<br>有任何使用问题都可以问我。</div>';
      return;
    }
    msgsEl.innerHTML = messages.map(m => {
      const streaming = m._streaming ? '<span class="hc-cursor"></span>' : '';
      return `<div class="hc-msg ${m.role}"><div class="hc-bubble">${escHtml(m.content)}${streaming}</div></div>`;
    }).join('');
    scrollBottom();
  }

  function escHtml(s) {
    return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  // ── Toggle ──
  btn.addEventListener('click', () => { open = true; btn.style.display = 'none'; panel.classList.add('open'); loadHistory(); });
  document.getElementById('hc-close').addEventListener('click', () => { open = false; btn.style.display = 'flex'; panel.classList.remove('open'); });

  // ── History ──
  async function loadHistory() {
    if (loaded) return;
    try {
      const r = await fetch(API_BASE + '/chat/history?site=' + SITE, { headers: authHeaders() });
      if (!r.ok) return;
      const d = await r.json();
      messages = d.messages || [];
      remaining = d.remaining ?? 20;
      loaded = true;
      updateRemaining();
      renderMessages();
    } catch (e) { console.error('hustle-chat history', e); }
  }

  // ── Send ──
  async function send() {
    const msg = inputEl.value.trim();
    if (!msg || sending) return;
    if (remaining <= 0) { alert('每小时最多提问 20 次，请稍后再试'); return; }

    inputEl.value = '';
    sending = true;
    sendBtn.disabled = true;
    sendBtn.textContent = '…';

    messages.push({ role: 'user', content: msg });
    const assistantMsg = { role: 'assistant', content: '', _streaming: true };
    messages.push(assistantMsg);
    remaining = Math.max(0, remaining - 1);
    updateRemaining();
    renderMessages();

    try {
      const resp = await fetch(API_BASE + '/chat', {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ message: msg, site: SITE }),
      });

      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        assistantMsg.content = err.detail || '请求失败，请重试';
        assistantMsg._streaming = false;
        renderMessages();
        return;
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        while (buffer.includes('\n')) {
          const idx = buffer.indexOf('\n');
          const line = buffer.slice(0, idx).trim();
          buffer = buffer.slice(idx + 1);

          if (!line.startsWith('data:')) continue;
          const payload = line.slice(5).trim();
          if (payload === '[DONE]') break;

          try {
            const obj = JSON.parse(payload);
            if (obj.content) { assistantMsg.content += obj.content; renderMessages(); }
            if (obj.error) { assistantMsg.content += '\n⚠ ' + obj.error; }
          } catch (e) {}
        }
      }
    } catch (e) {
      assistantMsg.content = assistantMsg.content || '网络错误，请重试';
    } finally {
      assistantMsg._streaming = false;
      sending = false;
      sendBtn.disabled = false;
      sendBtn.textContent = '发送';
      renderMessages();
    }
  }

  sendBtn.addEventListener('click', send);
  inputEl.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); send(); } });
})();
