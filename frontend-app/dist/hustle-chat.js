/**
 * Hustle AI Chat Widget — standalone, zero-dependency, Shadow DOM isolated.
 * Usage: <script src="/hustle-chat.js" data-site="admin"></script>
 */
(function () {
  const SCRIPT = document.currentScript;
  const SITE = (SCRIPT && SCRIPT.getAttribute('data-site')) || 'auto';
  const API_BASE = '/api/v1/agent';
  let open = false, sending = false, remaining = 20, loaded = false;
  let messages = [];

  function getToken() {
    return localStorage.getItem('admin_token') || localStorage.getItem('access_token') || localStorage.getItem('token') || '';
  }
  function authHeaders() {
    return { 'Authorization': 'Bearer ' + getToken(), 'Content-Type': 'application/json' };
  }

  var btnBottom = SITE === 'go' ? '24px' : '24px';
  var btnBottomMobile = SITE === 'go' ? '16px' : '16px';

  // ── Host element with Shadow DOM ──
  const host = document.createElement('div');
  host.id = 'hustle-chat-host';
  host.style.cssText = 'position:fixed;bottom:0;right:0;z-index:99999;pointer-events:none;';
  document.body.appendChild(host);

  const shadow = host.attachShadow({ mode: 'open' });

  const style = document.createElement('style');
  style.textContent = `
    *{box-sizing:border-box;margin:0;padding:0}
    :host{all:initial}

    #btn{
      position:fixed;bottom:${btnBottom};right:24px;
      width:48px;height:48px;border-radius:50%;
      background:#f0b90b;color:#1e2329;border:none;cursor:pointer;
      display:flex;align-items:center;justify-content:center;
      box-shadow:0 2px 8px rgba(0,0,0,.3);transition:background .2s;
      pointer-events:auto;
    }
    #btn:hover{background:#f5d245}
    #btn svg{width:24px;height:24px;display:block;flex-shrink:0}

    #panel{
      position:fixed;bottom:24px;right:24px;
      width:400px;height:520px;
      background:#181a20;border:1px solid #2b3139;border-radius:12px;
      display:none;flex-direction:column;overflow:hidden;
      font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
      font-size:14px;line-height:1.5;color:#eaecef;
      pointer-events:auto;
    }
    #panel.open{display:flex}

    .hdr{display:flex;align-items:center;justify-content:space-between;padding:12px 16px;border-bottom:1px solid #2b3139;background:#1e2329;flex-shrink:0}
    .hdr-l{display:flex;align-items:center;gap:8px}
    .logo{width:28px;height:28px;border-radius:6px;background:#f0b90b;display:flex;align-items:center;justify-content:center;color:#1e2329;font-weight:700;font-size:12px;flex-shrink:0}
    .title{font-weight:600;font-size:14px;color:#eaecef}
    .badge{font-size:10px;padding:2px 6px;background:#181a20;border-radius:4px;color:#848e9c}
    .hdr-r{display:flex;align-items:center;gap:8px}
    .remain{font-size:10px;color:#848e9c}
    .clear-btn{background:none;border:none;color:#848e9c;font-size:14px;cursor:pointer;padding:2px 4px;display:flex;align-items:center;border-radius:4px;transition:color .2s,background .2s}
    .clear-btn:hover{color:#f6465d;background:rgba(246,70,93,.1)}
    .clear-btn svg{width:16px;height:16px}
    .close-btn{background:none;border:none;color:#848e9c;font-size:22px;cursor:pointer;line-height:1;padding:0 2px;display:flex;align-items:center}
    .close-btn:hover{color:#eaecef}

    .msgs{flex:1;overflow-y:auto;padding:12px 16px;display:flex;flex-direction:column;gap:10px;min-height:0}
    .empty{text-align:center;color:#848e9c;font-size:12px;padding:32px 0;line-height:1.8}
    .msg{display:flex;position:relative}
    .msg.user{justify-content:flex-end}
    .msg.assistant{justify-content:flex-start}
    .bubble{max-width:85%;padding:8px 12px;border-radius:8px;font-size:12px;line-height:1.6;white-space:pre-wrap;word-break:break-word}
    .msg.user .bubble{background:rgba(240,185,11,.15);color:#eaecef;border:1px solid rgba(240,185,11,.3)}
    .msg.assistant .bubble{background:#1e2329;color:#eaecef;border:1px solid #2b3139}
    .del-btn{display:none;position:absolute;top:-6px;background:#2b3139;border:1px solid #363c46;color:#848e9c;width:18px;height:18px;border-radius:50%;font-size:11px;line-height:1;cursor:pointer;align-items:center;justify-content:center;padding:0;transition:color .15s,border-color .15s}
    .msg.user .del-btn{left:-6px}
    .msg.assistant .del-btn{right:-6px}
    .msg:hover .del-btn{display:flex}
    .del-btn:hover{color:#f6465d;border-color:#f6465d}
    .cursor{display:inline-block;width:6px;height:14px;background:rgba(240,185,11,.6);margin-left:2px;vertical-align:middle;animation:blink 1s infinite}
    @keyframes blink{0%,100%{opacity:1}50%{opacity:0}}

    .input-area{padding:12px 16px;border-top:1px solid #2b3139;background:#1e2329;display:flex;gap:8px;flex-shrink:0}
    .inp{flex:1;min-width:0;background:#181a20;border:1px solid #2b3139;border-radius:8px;padding:8px 12px;font-size:12px;color:#eaecef;outline:none;height:36px;font-family:inherit}
    .inp:focus{border-color:#f0b90b}
    .inp::placeholder{color:#848e9c}
    .send-btn{padding:0 16px;height:36px;background:#f0b90b;color:#1e2329;border:none;border-radius:8px;font-size:12px;font-weight:600;cursor:pointer;white-space:nowrap;flex-shrink:0;font-family:inherit}
    .send-btn:hover{background:#f5d245}
    .send-btn:disabled{opacity:.4;cursor:default}

    @media(max-width:640px){
      #btn{width:${SITE === 'go' ? '56px' : '42px'};height:${SITE === 'go' ? '56px' : '42px'};right:16px;bottom:${btnBottomMobile}}
      #btn svg{width:${SITE === 'go' ? '26px' : '20px'};height:${SITE === 'go' ? '26px' : '20px'}}
      #panel{top:0;left:0;right:0;bottom:0;width:100%;height:100%;border-radius:0;border:none}
    }
  `;
  shadow.appendChild(style);

  // ── DOM ──
  const btn = document.createElement('button');
  btn.id = 'btn';
  btn.title = 'Hustle AI 助手';
  btn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z"/></svg>';

  const panel = document.createElement('div');
  panel.id = 'panel';
  panel.innerHTML = `
    <div class="hdr">
      <div class="hdr-l">
        <div class="logo">H</div>
        <span class="title">Hustle</span>
        <span class="badge">AI 助手</span>
      </div>
      <div class="hdr-r">
        <span class="remain" id="remain"></span>
        <button class="clear-btn" id="clear-btn" title="清空对话"><svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg></button>
        <button class="close-btn" id="close-btn">&times;</button>
      </div>
    </div>
    <div class="msgs" id="msgs"></div>
    <div class="input-area">
      <input class="inp" id="inp" placeholder="输入问题…">
      <button class="send-btn" id="send-btn">发送</button>
    </div>
  `;

  shadow.appendChild(btn);
  shadow.appendChild(panel);

  const msgsEl = shadow.getElementById('msgs');
  const inputEl = shadow.getElementById('inp');
  const sendBtn = shadow.getElementById('send-btn');
  const remainEl = shadow.getElementById('remain');
  const clearBtn = shadow.getElementById('clear-btn');

  function updateRemaining() { remainEl.textContent = remaining + '/20'; }
  updateRemaining();

  function scrollBottom() {
    requestAnimationFrame(() => { msgsEl.scrollTop = msgsEl.scrollHeight; });
  }

  function escHtml(s) {
    return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  function renderMessages() {
    if (!messages.length) {
      msgsEl.innerHTML = '<div class="empty">你好！我是 Hustle，AI 助手。<br>有任何使用问题都可以问我。</div>';
      return;
    }
    msgsEl.innerHTML = messages.map(function(m) {
      var streaming = m._streaming ? '<span class="cursor"></span>' : '';
      var delBtn = (m.id && !m._streaming) ? '<button class="del-btn" data-id="' + m.id + '">×</button>' : '';
      return '<div class="msg ' + m.role + '"><div class="bubble">' + escHtml(m.content) + streaming + '</div>' + delBtn + '</div>';
    }).join('');
    scrollBottom();
  }

  // ── Toggle ──
  btn.addEventListener('click', function() {
    open = true;
    btn.style.display = 'none';
    panel.classList.add('open');
    loadHistory();
  });
  shadow.getElementById('close-btn').addEventListener('click', function() {
    open = false;
    btn.style.display = 'flex';
    panel.classList.remove('open');
  });

  // ── History ──
  async function loadHistory() {
    if (loaded) return;
    try {
      var r = await fetch(API_BASE + '/chat/history?site=' + SITE, { headers: authHeaders() });
      if (!r.ok) return;
      var d = await r.json();
      messages = (d.messages || []).map(function(m) {
        return { id: m.id, role: m.role, content: m.content };
      });
      remaining = d.remaining != null ? d.remaining : 20;
      loaded = true;
      updateRemaining();
      renderMessages();
    } catch (e) { console.error('hustle-chat history', e); }
  }

  // ── Delete single message ──
  msgsEl.addEventListener('click', async function(e) {
    var target = e.target.closest('.del-btn');
    if (!target) return;
    var msgId = target.getAttribute('data-id');
    if (!msgId) return;
    try {
      var r = await fetch(API_BASE + '/chat/messages/' + msgId, {
        method: 'DELETE',
        headers: authHeaders(),
      });
      if (r.ok) {
        messages = messages.filter(function(m) { return String(m.id) !== String(msgId); });
        renderMessages();
      }
    } catch (e) { console.error('hustle-chat delete', e); }
  });

  // ── Clear all ──
  clearBtn.addEventListener('click', async function() {
    if (!messages.length) return;
    if (!confirm('确定清空所有对话记录？此操作不可撤销。')) return;
    try {
      var r = await fetch(API_BASE + '/chat/history?site=' + SITE, {
        method: 'DELETE',
        headers: authHeaders(),
      });
      if (r.ok) {
        messages = [];
        renderMessages();
      }
    } catch (e) { console.error('hustle-chat clear', e); }
  });

  // ── Send ──
  async function send() {
    var msg = inputEl.value.trim();
    if (!msg || sending) return;
    if (remaining <= 0) { alert('每小时最多提问 20 次，请稍后再试'); return; }

    inputEl.value = '';
    sending = true;
    sendBtn.disabled = true;
    sendBtn.textContent = '…';

    messages.push({ role: 'user', content: msg });
    var assistantMsg = { role: 'assistant', content: '', _streaming: true };
    messages.push(assistantMsg);
    remaining = Math.max(0, remaining - 1);
    updateRemaining();
    renderMessages();

    try {
      var resp = await fetch(API_BASE + '/chat', {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ message: msg, site: SITE }),
      });

      if (!resp.ok) {
        var err = await resp.json().catch(function() { return {}; });
        assistantMsg.content = err.detail || '请求失败，请重试';
        assistantMsg._streaming = false;
        renderMessages();
        return;
      }

      var reader = resp.body.getReader();
      var decoder = new TextDecoder();
      var buffer = '';

      while (true) {
        var chunk = await reader.read();
        if (chunk.done) break;
        buffer += decoder.decode(chunk.value, { stream: true });
        while (buffer.includes('\n')) {
          var idx = buffer.indexOf('\n');
          var line = buffer.slice(0, idx).trim();
          buffer = buffer.slice(idx + 1);
          if (!line.startsWith('data:')) continue;
          var payload = line.slice(5).trim();
          if (payload === '[DONE]') break;
          try {
            var obj = JSON.parse(payload);
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
      setTimeout(function() { loaded = false; loadHistory(); }, 800);
    }
  }

  sendBtn.addEventListener('click', send);
  inputEl.addEventListener('keydown', function(e) { if (e.key === 'Enter') { e.preventDefault(); send(); } });
})();
