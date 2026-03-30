// Agent-Nimi — App JS
'use strict';

// ── State ──────────────────────────────────────────────────────────────────
let currentConvId = null;
let isStreaming = false;
let abortController = null;
let currentAssistantDiv = null;
let currentContentDiv = null;
let autoScrollEnabled = true;
let activeTerminals = {};
let attachedFiles = [];
let currentMode = 'agent';
let pendingDeleteConvId = null;
let pendingDeleteResetTimer = null;
let pendingClearRecent = false;
let pendingClearRecentTimer = null;
let currentStatusEl = null;
let currentRoleTrack = null;
let currentProgressEl = null;
let currentProgressFill = null;
let streamStartTime = null;
let streamElapsedTimer = null;

// ── Bootstrap ──────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  // Sidebar toggle
  document.getElementById('sidebar-toggle')?.addEventListener('click', () => {
    document.getElementById('sidebar').classList.toggle('collapsed');
  });
  document.getElementById('topbar-toggle')?.addEventListener('click', () => {
    document.getElementById('sidebar').classList.remove('collapsed');
  });

  // New chat
  document.getElementById('btn-new-chat')?.addEventListener('click', newChat);
  document.getElementById('btn-clear-recents')?.addEventListener('click', requestClearRecent);

  // Clear
  document.getElementById('btn-clear')?.addEventListener('click', clearChat);

  // Send / stop
  document.getElementById('btn-send')?.addEventListener('click', sendMessage);
  document.getElementById('btn-stop')?.addEventListener('click', stopGeneration);

  // Textarea
  setupTextarea();

  // Quick buttons
  document.querySelectorAll('.quick-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const text = btn.dataset.msg;
      if (text) {
        document.getElementById('user-input').value = text;
        sendMessage();
      }
    });
  });

  // Provider
  document.getElementById('provider-select')?.addEventListener('change', onProviderChange);
  document.getElementById('model-select')?.addEventListener('change', onModelChange);
  document.getElementById('btn-set-key')?.addEventListener('click', setApiKey);

  // Router
  document.getElementById('router-toggle')?.addEventListener('change', e => setRouter(e.target.checked));
  document.getElementById('btn-router-stats')?.addEventListener('click', toggleRouterStats);

  // Monitor
  document.getElementById('btn-monitor-start')?.addEventListener('click', startMonitor);
  document.getElementById('btn-monitor-stop')?.addEventListener('click', stopMonitor);

  // Tool modal
  document.getElementById('btn-create-tool')?.addEventListener('click', openToolModal);
  document.getElementById('modal-close')?.addEventListener('click', closeToolModal);
  document.getElementById('btn-modal-cancel')?.addEventListener('click', closeToolModal);
  document.getElementById('btn-tool-generate')?.addEventListener('click', generateTool);
  document.getElementById('btn-tool-save')?.addEventListener('click', saveGeneratedTool);
  document.getElementById('btn-tool-back')?.addEventListener('click', toolGoBack);
  document.getElementById('tool-modal')?.addEventListener('click', e => {
    if (e.target.id === 'tool-modal') closeToolModal();
  });

  // Power
  document.getElementById('btn-shutdown')?.addEventListener('click', shutdownServer);
  document.getElementById('btn-restart')?.addEventListener('click', restartServer);

  // File attach
  document.getElementById('btn-attach')?.addEventListener('click', () => document.getElementById('file-input')?.click());
  document.getElementById('file-input')?.addEventListener('change', handleFileAttach);

  // Mode selector
  document.querySelectorAll('.mode-btn').forEach(btn =>
    btn.addEventListener('click', () => setMode(btn.dataset.mode))
  );

  // Auto-scroll detection
  const cc = document.getElementById('chat-container');
  if (cc) cc.addEventListener('scroll', () => {
    autoScrollEnabled = cc.scrollTop + cc.clientHeight >= cc.scrollHeight - 60;
  });

  // Init
  loadStatus();
  loadConversations();
  loadRouterStatus();
  loadTools();
});

// ── Settings toggle ────────────────────────────────────────────────────────
function toggleSettings(name) {
  const body = document.getElementById('settings-body-' + name);
  const chev = document.getElementById('chevron-' + name);
  if (!body) return;
  const open = body.style.display === 'flex';
  body.style.display = open ? 'none' : 'flex';
  if (chev) chev.classList.toggle('open', !open);
}

// ── Conversations ───────────────────────────────────────────────────────────
async function loadConversations() {
  try {
    const r = await fetch('/api/conversations', {cache:'no-store'});
    const data = await r.json();
    renderConvList(data.conversations || []);
  } catch(e) {}
}

function renderConvList(convs) {
  const list = document.getElementById('conv-list');
  if (!list) return;
  const savedPendingDeleteId = pendingDeleteConvId;
  resetConversationDeleteConfirmation();
  resetClearRecentConfirmation();
  list.innerHTML = '';
  convs.forEach(c => {
    const item = document.createElement('div');
    item.className = 'conv-item' + (c.id === currentConvId ? ' active' : '');
    item.dataset.id = c.id;
    item.innerHTML = `<span class="conv-title">${escapeHtml(c.title || 'New Chat')}</span>
      <button class="conv-del" title="Delete conversation">&#x2715;</button>`;
    item.addEventListener('click', () => switchConversation(c.id));
    item.querySelector('.conv-del').addEventListener('click', e => {
      e.stopPropagation();
      requestDeleteConversation(item, c.id);
    });
    item.querySelector('.conv-title').addEventListener('dblclick', e => {
      e.stopPropagation(); startRename(item, c.id, c.title || 'New Chat');
    });
    list.appendChild(item);
  });
  // Restore pending delete confirmation if list was re-rendered mid-confirm
  if (savedPendingDeleteId) {
    const pendingItem = list.querySelector(`[data-id="${savedPendingDeleteId}"]`);
    if (pendingItem) {
      const btn = pendingItem.querySelector('.conv-del');
      if (btn) {
        pendingDeleteConvId = savedPendingDeleteId;
        btn.classList.add('confirm');
        btn.textContent = '!';
        btn.title = 'Press again to delete';
        pendingDeleteResetTimer = setTimeout(() => {
          resetConversationDeleteConfirmation();
        }, 3000);
      }
    }
  }
}

async function requestClearRecent() {
  const btn = document.getElementById('btn-clear-recents');
  if (!btn) return;

  if (pendingClearRecent) {
    resetClearRecentConfirmation();
    await clearRecentConversations();
    return;
  }

  pendingClearRecent = true;
  btn.classList.add('confirm');
  btn.textContent = 'Confirm';
  btn.title = 'Press again to archive and clear recent chats';
  pendingClearRecentTimer = setTimeout(() => {
    resetClearRecentConfirmation();
  }, 2500);
}

function resetClearRecentConfirmation() {
  if (pendingClearRecentTimer) {
    clearTimeout(pendingClearRecentTimer);
    pendingClearRecentTimer = null;
  }
  pendingClearRecent = false;
  const btn = document.getElementById('btn-clear-recents');
  if (!btn) return;
  btn.classList.remove('confirm');
  btn.textContent = 'Clear';
  btn.title = 'Clear recent list';
}

async function requestDeleteConversation(item, id) {
  const button = item?.querySelector('.conv-del');
  if (!button) return;

  if (pendingDeleteConvId === id) {
    resetConversationDeleteConfirmation();
    await deleteConversation(id, item);
    return;
  }

  resetConversationDeleteConfirmation();
  pendingDeleteConvId = id;
  button.classList.add('confirm');
  button.textContent = '!';
  button.title = 'Press again to delete';
  pendingDeleteResetTimer = setTimeout(() => {
    resetConversationDeleteConfirmation();
  }, 3500);
}

function resetConversationDeleteConfirmation() {
  if (pendingDeleteResetTimer) {
    clearTimeout(pendingDeleteResetTimer);
    pendingDeleteResetTimer = null;
  }
  document.querySelectorAll('.conv-del.confirm').forEach(btn => {
    btn.classList.remove('confirm');
    btn.textContent = '✕';
    btn.title = 'Delete conversation';
  });
  pendingDeleteConvId = null;
}

async function newChat() {
  try {
    const r = await fetch('/api/conversations', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({title:'New Chat'})});
    const data = await r.json();
    currentConvId = data.id;
    document.getElementById('messages').innerHTML = '';
    document.getElementById('welcome').style.display = '';
    document.getElementById('topbar-title').textContent = 'New Chat';
    await loadConversations();
    document.getElementById('user-input')?.focus();
  } catch(e) {}
}

async function switchConversation(id) {
  if (id === currentConvId && isStreaming) return;
  try {
    const r = await fetch('/api/conversations/' + id + '/load', {method:'POST'});
    if (!r.ok) return;
    const data = await r.json();
    const conv = data.conversation || data;
    currentConvId = id;
    document.getElementById('topbar-title').textContent = conv.title || 'Chat';
    const msgs = document.getElementById('messages');
    msgs.innerHTML = '';
    (conv.messages || []).forEach(m => {
      if (m.role === 'user') appendUserMessage(m.content);
      else if (m.role === 'assistant') appendAssistantHistory(m.content);
    });
    document.getElementById('welcome').style.display = msgs.children.length ? 'none' : '';
    await loadConversations();
    scrollToBottom();
  } catch(e) {}
}

async function deleteConversation(id, item = null) {
  const resp = await fetch('/api/conversations/' + id, {method:'DELETE', cache:'no-store'});
  if (!resp.ok) return;
  item?.remove();
  if (id === currentConvId) {
    currentConvId = null;
    document.getElementById('messages').innerHTML = '';
    document.getElementById('welcome').style.display = '';
    document.getElementById('topbar-title').textContent = 'Agent Nimi';
  }
  if (!document.getElementById('conv-list')?.children.length) {
    document.getElementById('welcome').style.display = '';
  }
  await loadConversations();
}

async function clearRecentConversations() {
  const resp = await fetch('/api/conversations/clear', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    cache:'no-store'
  });
  if (!resp.ok) return;
  currentConvId = null;
  document.getElementById('messages').innerHTML = '';
  document.getElementById('welcome').style.display = '';
  document.getElementById('topbar-title').textContent = 'Agent Nimi';
  const list = document.getElementById('conv-list');
  if (list) list.innerHTML = '';
  await loadConversations();
}

function startRename(item, id, current) {
  const titleEl = item.querySelector('.conv-title');
  const inp = document.createElement('input');
  inp.value = current;
  titleEl.innerHTML = '';
  titleEl.appendChild(inp);
  inp.focus(); inp.select();
  const commit = async () => {
    const title = inp.value.trim() || current;
    await fetch('/api/conversations/' + id, {method:'PUT', headers:{'Content-Type':'application/json'}, body: JSON.stringify({title})});
    if (id === currentConvId) document.getElementById('topbar-title').textContent = title;
    await loadConversations();
  };
  inp.addEventListener('blur', commit);
  inp.addEventListener('keydown', e => { if (e.key==='Enter') inp.blur(); if (e.key==='Escape') { inp.value=current; inp.blur(); }});
}

// ── Sending messages ────────────────────────────────────────────────────────
// ── File attachment helpers ─────────────────────────────────────────────────
function setMode(mode) {
  currentMode = mode;
  document.querySelectorAll('.mode-btn').forEach(b => b.classList.toggle('active', b.dataset.mode === mode));
}

function handleFileAttach(e) {
  Array.from(e.target.files).forEach(f => {
    if (!attachedFiles.find(a => a.name === f.name && a.size === f.size)) attachedFiles.push(f);
  });
  e.target.value = '';
  renderFileChips();
}

function renderFileChips() {
  const c = document.getElementById('file-chips');
  if (!c) return;
  if (!attachedFiles.length) { c.style.display = 'none'; return; }
  c.style.display = 'flex';
  c.innerHTML = attachedFiles.map((f, i) =>
    `<div class="file-chip"><span class="file-chip-name">${escapeHtml(f.name)}</span><span class="file-chip-size">${fmtBytes(f.size)}</span><button class="file-chip-rm" onclick="removeFile(${i})">&times;</button></div>`
  ).join('');
}

function removeFile(i) { attachedFiles.splice(i, 1); renderFileChips(); }

function fmtBytes(n) {
  if (n < 1024) return n + 'B';
  if (n < 1048576) return (n/1024).toFixed(1) + 'KB';
  return (n/1048576).toFixed(1) + 'MB';
}

function readFileText(file) {
  return new Promise(resolve => {
    const textTypes = ['text/', 'application/json', 'application/xml', 'application/javascript', 'application/yaml'];
    const isText = !file.type || textTypes.some(t => file.type.startsWith(t));
    if (!isText) { resolve(`[Binary: ${file.name} (${file.type||'unknown'}, ${fmtBytes(file.size)})]`); return; }
    const r = new FileReader();
    r.onload = e => resolve(e.target.result);
    r.onerror = () => resolve(`[Error reading ${file.name}]`);
    r.readAsText(file);
  });
}

async function sendMessage() {
  const input = document.getElementById('user-input');
  const text = input.value.trim();
  if (!text || isStreaming) return;

  // Read any attached files
  let fileSuffix = '';
  let fileLabels = [];
  if (attachedFiles.length) {
    const contents = await Promise.all(attachedFiles.map(readFileText));
    fileSuffix = contents.map((c, i) => `\n\n--- Attached: ${attachedFiles[i].name} ---\n${c}`).join('');
    fileLabels = attachedFiles.map(f => f.name);
    attachedFiles = [];
    renderFileChips();
  }

  const fullText = text + fileSuffix;

  // Get provider config
  const provider = document.getElementById('provider-select')?.value || 'grok';
  const model = document.getElementById('model-select')?.value || '';
  const apiKey = document.getElementById('api-key-input')?.value || '';

  // Ensure a conversation exists
  if (!currentConvId) {
    try {
      const r = await fetch('/api/conversations', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({title: text.slice(0,40)})});
      const d = await r.json();
      currentConvId = d.id;
      document.getElementById('topbar-title').textContent = text.slice(0,40);
    } catch(e) {}
  }

  // Show welcome gone
  document.getElementById('welcome').style.display = 'none';
  input.value = '';
  resizeTextarea(input);

  // Show user message (with file badge if any)
  appendUserMessage(text, fileLabels);
  createAssistantMessage();

  isStreaming = true;
  abortController = new AbortController();
  document.getElementById('btn-send').style.display = 'none';
  document.getElementById('btn-stop').classList.add('visible');

  try {
    const resp = await fetch('/api/chat', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({message: fullText, provider, model, api_key: apiKey, conversation_id: currentConvId, mode: currentMode}),
      signal: abortController.signal
    });
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      buf += decoder.decode(value, {stream:true});
      const lines = buf.split('\n');
      buf = lines.pop();
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try { handleEvent(JSON.parse(line.slice(6))); } catch(e) {}
        }
      }
    }
  } catch(e) {
    if (e.name !== 'AbortError') appendTextChunk('[Connection error]');
  } finally {
    finalizeMessage();
    isStreaming = false;
    abortController = null;
    document.getElementById('btn-send').style.display = '';
    document.getElementById('btn-stop').classList.remove('visible');
    loadStatus();
    loadConversations();
  }
}

function stopGeneration() {
  abortController?.abort();
}

async function clearChat() {
  if (!confirm('Clear chat history?')) return;
  await fetch('/api/clear', {method:'POST'});
  document.getElementById('messages').innerHTML = '';
  document.getElementById('welcome').style.display = '';
  currentConvId = null;
  document.getElementById('topbar-title').textContent = 'Agent Nimi';
  await loadConversations();
}

// ── Streaming event handler ─────────────────────────────────────────────────
function handleEvent(ev) {
  if (!ev || !ev.type) return;
  const pills = currentAssistantDiv?.querySelector('.event-pills');
  const addPill = (cls, html) => {
    if (!pills) return;
    const p = document.createElement('div');
    p.className = 'pill pill-flash ' + cls;
    p.innerHTML = html;
    pills.appendChild(p);
    scrollToBottom();
  };
  const renderToolBadges = (tools) => {
    const list = Array.isArray(tools) ? tools : [];
    if (!list.length) return '';
    const visible = list.slice(0, 4);
    const hidden = list.slice(4);
    const visibleHtml = visible.map(t =>
      '<span class="tool-mini-badge">' + escapeHtml(String(t)) + '</span>'
    ).join('');
    const hiddenHtml = hidden.map(t =>
      '<span class="tool-mini-badge tool-mini-badge-extra" style="display:none">' + escapeHtml(String(t)) + '</span>'
    ).join('');
    const moreBtn = hidden.length
      ? '<button type="button" class="tool-mini-more" onclick="toggleToolBadgeOverflow(this)">+' + hidden.length + '</button>'
      : '';
    return ' <span class="tool-mini-badges">' + visibleHtml + hiddenHtml + moreBtn + '</span>';
  };

  switch(ev.type) {
    case 'task_classified':
      addPill('task-classified', '&#x1F4CB; ' + escapeHtml(ev.task_type || 'task'));
      setStatus(escapeHtml(ev.task_type || 'task') + '…');
      setReasoningProgress(8, 'task classified');
      break;
    case 'agent_start':
      addPill('agent-start', '&#x25B6; agent starting&hellip;');
      setStatus('agent starting…');
      setReasoningProgress(12, 'agent starting');
      break;
    case 'mode_switched':
      addPill('thinking-pill', '&#x1F504; mode switched &rarr; ' + escapeHtml(ev.mode || ''));
      setMode(ev.mode || currentMode);
      break;
    case 'routed': {
      const rtEl = document.getElementById('router-routed-to');
      if (rtEl) { rtEl.textContent = '→ ' + (ev.model || ''); rtEl.style.display = 'block'; }
      addPill('routed-pill', '&#x1F500; routed &rarr; ' + escapeHtml(ev.model || ''));
      setReasoningProgress(18, 'provider routed');
      break;
    }
    case 'multiagent_start': {
      addPill('agent-start', '&#x1F9E0; multiagent start (' + escapeHtml(String((ev.roles || []).length)) + ' roles)');
      setStatus('spawning roles…');
      setReasoningProgress(22, 'multiagent started');
      // Build role progress track
      if (currentAssistantDiv) {
        const rt = document.createElement('div');
        rt.className = 'role-track';
        (ev.roles || []).forEach(r => {
          const node = document.createElement('span');
          node.className = 'role-node pending';
          node.dataset.role = r;
          node.textContent = r;
          rt.appendChild(node);
        });
        const statusBar = currentAssistantDiv.querySelector('.stream-status');
        statusBar ? statusBar.before(rt) : currentAssistantDiv.querySelector('.msg-bubble').prepend(rt);
        currentRoleTrack = rt;
      }
      break;
    }
    case 'subtask_escalated':
      addPill('thinking-pill', '&#x26A0; escalated ' + escapeHtml(ev.role || '') + ' from ' + escapeHtml(ev.from || ''));
      break;
    case 'subtask_stuck':
      addPill('tool-blocked', '&#x26D4; stuck: ' + escapeHtml(ev.role || '') + ' (' + escapeHtml(ev.task_type || '') + ')');
      break;
    case 'subtask_routed': {
      const tools = renderToolBadges(ev.recommended_tools || []);
      addPill(
        'routed-pill',
        '&#x1F9E9; ' + escapeHtml(ev.role || '') + ' &rarr; ' + escapeHtml(ev.provider || '') +
        (ev.model ? ':' + escapeHtml(ev.model) : '') + tools
      );
      // Mark role as running in tracker
      if (currentRoleTrack) {
        const node = currentRoleTrack.querySelector('[data-role="' + CSS.escape(ev.role || '') + '"]');
        if (node) { node.classList.remove('pending'); node.classList.add('running'); }
      }
      setStatus((ev.role || 'role') + ' → ' + (ev.provider || '') + (ev.model ? ':' + ev.model : '') + '…');
      setReasoningProgress(36, 'subtask running');
      break;
    }
    case 'subtask_done': {
      // Mark role as done in tracker
      if (currentRoleTrack) {
        const node = currentRoleTrack.querySelector('[data-role="' + CSS.escape(ev.role || '') + '"]');
        if (node) { node.classList.remove('running'); node.classList.add('done'); }
      }
      // Check if all roles done -> update status
      const runningNodes = currentRoleTrack?.querySelectorAll('.role-node.running');
      const pendingNodes = currentRoleTrack?.querySelectorAll('.role-node.pending');
      if (!runningNodes?.length && !pendingNodes?.length) {
        setStatus('synthesizing…');
      } else {
        setStatus('✓ ' + (ev.role || 'role') + ' done · ' + (ev.chars || 0) + ' chars');
      }
      bumpReasoningProgress(4, 'subtask done');
      break;
    }
    case 'boss_routed':
      addPill('routed-pill', '&#x1F451; boss synthesis &rarr; ' + escapeHtml(ev.provider || '') + (ev.model ? ':' + escapeHtml(ev.model) : ''));
      setStatus('boss synthesizing…');
      setReasoningProgress(70, 'synthesizing');
      break;
    case 'boss_approved':
      addPill('agent-done-pill', '&#x2714; synthesis approved');
      setStatus('finalizing…');
      setReasoningProgress(88, 'approved');
      break;
    case 'boss_refinement':
      addPill('thinking-pill', '&#x1F504; refining synthesis (attempt ' + (ev.attempt || '') + ')');
      setStatus('refining…');
      bumpReasoningProgress(2, 'refining');
      break;
    case 'multiagent_replan':
      addPill('thinking-pill', '&#x1F501; replanning (' + (ev.new_subtasks || 0) + ' new tasks)');
      setStatus('replanning…');
      bumpReasoningProgress(2, 'replanning');
      break;
    case 'mission_iteration':
      addPill('thinking-pill', '&#x1F504; mission iter ' + (ev.iteration||1) + '/' + (ev.max||'?') + (ev.blockers ? ' (' + ev.blockers + ' blockers)' : ''));
      setStatus('mission iteration ' + (ev.iteration||1) + '…');
      bumpReasoningProgress(2, 'mission iteration');
      break;
    case 'mission_adapting':
      addPill('agent-done-pill', '&#x1F9E0; adapting &mdash; pivoting strategy&#8230;');
      setStatus('adapting… finding new approach');
      bumpReasoningProgress(2, 'adapting');
      break;
    case 'multiagent_done':
      // All role nodes done
      currentRoleTrack?.querySelectorAll('.role-node').forEach(n => { n.classList.remove('running','pending'); n.classList.add('done'); });
      setStatus('done');
      setReasoningProgress(100, 'done');
      break;
    case 'iteration':
      addPill('thinking-pill', '&#x1F914; iteration ' + (ev.current || ev.iteration || ''));
      bumpReasoningProgress(3, 'iteration');
      break;
    case 'llm_call_start':
      setStatus('thinking…');
      bumpReasoningProgress(2, 'thinking');
      if (!currentAssistantDiv?.querySelector('.typing-dot')) {
        const td = document.createElement('div');
        td.className = 'typing-dot';
        td.innerHTML = '<span></span><span></span><span></span>';
        currentContentDiv?.appendChild(td);
        scrollToBottom();
      }
      break;
    case 'llm_call_done':
      currentAssistantDiv?.querySelector('.typing-dot')?.remove();
      addPill('thinking-pill', '&#x26A1; ' + (ev.tokens||'') + ' tok ' + (ev.duration_ms ? (ev.duration_ms/1000).toFixed(1)+'s' : ''));
      setStatus('processing…');
      bumpReasoningProgress(4, 'llm done');
      break;
    case 'safety_check':
      addPill('safety-pill', '&#x1F6E1; safety: ' + (ev.verdict||'ok'));
      break;
    case 'tool_start':
      createTerminalWidget(ev);
      setStatus('&#x1F528; ' + (ev.tool || 'tool') + '…');
      bumpReasoningProgress(6, 'tool running');
      break;
    case 'tool_result':
      finishTerminalWidget(ev);
      setStatus('✓ ' + (ev.tool || 'tool') + ' done');
      bumpReasoningProgress(8, 'tool complete');
      break;
    case 'learning':
      if (pills) {
        const p = document.createElement('div');
        p.className = 'pill learning-pill';
        p.innerHTML = '<span>&#x1F393; learning score: ' + (ev.score||'') + '</span>' +
          (ev.summary ? '<span style="font-size:10px;opacity:.8">' + escapeHtml(ev.summary) + '</span>' : '');
        pills.appendChild(p);
      }
      break;
    case 'agent_done':
      addPill('agent-done-pill', '&#x2705; done' + (ev.iterations ? ' (' + ev.iterations + ' iters)' : ''));
      currentRoleTrack?.querySelectorAll('.role-node').forEach(n => { n.classList.remove('running','pending'); n.classList.add('done'); });
      setStatus('done');
      setReasoningProgress(100, 'done');
      break;
    case 'tool_blocked':
      addPill('tool-blocked', '&#x26D4; blocked: ' + escapeHtml(ev.tool||''));
      addPill('tool-blocked', '&#x26A0; action blocked by safety');
      break;
    case 'reasoning_trace':
      addPill('thinking-pill', '&#x1F9E0; reasoning step ' + String(ev.step || ''));
      bumpReasoningProgress(3, 'reasoning');
      break;
    case 'reflection':
      addPill('thinking-pill', '&#x1F50D; reflection');
      bumpReasoningProgress(2, 'reflection');
      break;
    case 'provider_degraded':
      addPill('tool-blocked', '&#x26A0; provider degraded ' + escapeHtml(ev.from || '') + ' → ' + escapeHtml(ev.to || ''));
      bumpReasoningProgress(1, 'degraded');
      break;
    case 'reflexion_retry':
      addPill('thinking-pill', '&#x1F504; retry attempt ' + String(ev.attempt || ''));
      bumpReasoningProgress(2, 'retry');
      break;
    case 'workflow_tool_blocked':
      addPill('tool-blocked', '&#x26D4; workflow blocked ' + escapeHtml(ev.tool || ''));
      break;
    case 'tool_declined':
      addPill('tool-blocked', '&#x26D4; declined ' + escapeHtml(ev.tool || ''));
      break;
    case 'confirm_request':
      addPill('thinking-pill', '&#x1F6E1; confirmation required: ' + escapeHtml(ev.tool || ''));
      break;
    case 'steer':
      if (currentContentDiv) {
        const b = document.createElement('div');
        b.className = 'steer-bubble';
        b.textContent = ev.text || '';
        currentContentDiv.appendChild(b);
      }
      break;
    case 'text_chunk':
      appendTextChunk(ev.text || ev.content || '');
      break;
    case 'chunk':
      appendTextChunk(ev.content || ev.text || '');
      break;
    case 'done':
      if (ev.content && (!currentContentDiv || !currentContentDiv._rawText)) {
        appendTextChunk(ev.content);
      }
      break;
    case 'error':
      appendTextChunk('[Error: ' + (ev.message || ev.content || 'unknown') + ']');
      break;
    case 'stream_notice':
      addPill('thinking-pill', '&#x2139; ' + escapeHtml(ev.message || 'streaming notice'));
      break;
  }
  if (ev.conversation_id && !currentConvId) currentConvId = ev.conversation_id;
}

function toggleToolBadgeOverflow(btn) {
  const wrap = btn?.closest('.tool-mini-badges');
  if (!wrap) return;
  const extras = wrap.querySelectorAll('.tool-mini-badge-extra');
  if (!extras.length) return;
  const expanded = btn.dataset.expanded === '1';
  extras.forEach(el => {
    el.style.display = expanded ? 'none' : 'inline-flex';
  });
  btn.dataset.expanded = expanded ? '0' : '1';
  btn.textContent = expanded ? `+${extras.length}` : '−';
}

// ── Message DOM helpers ─────────────────────────────────────────────────────
function appendUserMessage(text, fileLabels) {
  const msgs = document.getElementById('messages');
  const div = document.createElement('div');
  div.className = 'message user';
  const files = (fileLabels && fileLabels.length)
    ? `<div class="user-files">${fileLabels.map(n => `<span class="user-file-chip">📎 ${escapeHtml(n)}</span>`).join('')}</div>`
    : '';
  div.innerHTML = `<div class="msg-bubble">${files}<span>${escapeHtml(text)}</span></div>`;
  msgs.appendChild(div);
  scrollToBottom();
}

function appendAssistantHistory(text) {
  const msgs = document.getElementById('messages');
  const div = document.createElement('div');
  div.className = 'message assistant';
  div.innerHTML = `<div class="msg-bubble"><div class="msg-text-segment">${renderMarkdown(text)}</div>
    <div class="msg-actions"><button class="msg-action-btn" onclick="copyMessageText(this)">Copy</button></div></div>`;
  msgs.appendChild(div);
}

function createAssistantMessage() {
  const msgs = document.getElementById('messages');
  const div = document.createElement('div');
  div.className = 'message assistant';
  div.innerHTML =
    '<div class="msg-bubble">' +
      '<div class="event-pills"></div>' +
      '<div class="stream-status"><span class="stream-spinner"></span><span class="stream-status-text">connecting…</span><span class="stream-elapsed"></span></div>' +
      '<div class="reasoning-progress"><div class="reasoning-progress-fill"></div><span class="reasoning-progress-label">booting</span></div>' +
      '<div class="msg-content"></div>' +
      '<div class="msg-actions"><button class="msg-action-btn" onclick="copyMessageText(this)">Copy</button></div>' +
    '</div>';
  msgs.appendChild(div);
  currentAssistantDiv = div;
  currentContentDiv = div.querySelector('.msg-content');
  currentStatusEl = div.querySelector('.stream-status');
  currentProgressEl = div.querySelector('.reasoning-progress');
  currentProgressFill = div.querySelector('.reasoning-progress-fill');
  setReasoningProgress(4, 'connecting');
  currentRoleTrack = null;
  streamStartTime = Date.now();
  if (streamElapsedTimer) clearInterval(streamElapsedTimer);
  streamElapsedTimer = setInterval(() => {
    const elEl = currentStatusEl?.querySelector('.stream-elapsed');
    if (elEl && streamStartTime) elEl.textContent = ((Date.now() - streamStartTime) / 1000).toFixed(1) + 's';
  }, 100);
  scrollToBottom();
}

function setStatus(text) {
  const t = currentStatusEl?.querySelector('.stream-status-text');
  if (t) t.textContent = text;
}

function appendTextChunk(text) {
  if (!currentContentDiv) return;
  // remove typing dot if present
  currentAssistantDiv?.querySelector('.typing-dot')?.remove();
  // accumulate raw text on the element
  if (!currentContentDiv._rawText) currentContentDiv._rawText = '';
  currentContentDiv._rawText += text;
  // Keep streaming lightweight: append plain text live, render markdown once at finalize.
  let live = currentContentDiv.querySelector('.msg-text-live');
  if (!live) {
    live = document.createElement('div');
    live.className = 'msg-text-live';
    currentContentDiv.appendChild(live);
  }
  live.textContent += text;
  bumpReasoningProgress(1, 'streaming');
  scrollToBottom();
}

function finalizeMessage() {
  if (currentContentDiv) {
    // Final markdown render after streaming text has arrived.
    const raw = currentContentDiv._rawText || '';
    if (raw) {
      let seg = currentContentDiv.querySelector('.msg-text-segment');
      if (!seg) {
        seg = document.createElement('div');
        seg.className = 'msg-text-segment';
        currentContentDiv.appendChild(seg);
      }
      seg.innerHTML = renderMarkdown(raw);
    }
    currentContentDiv.querySelector('.msg-text-live')?.remove();
  }
  setReasoningProgress(100, 'done');
  currentProgressEl?.classList.add('done');
  if (currentStatusEl) {
    currentStatusEl.classList.add('done');
    const toRemove = currentStatusEl;
    setTimeout(() => toRemove.remove(), 700);
    currentStatusEl = null;
  currentProgressEl = null;
  currentProgressFill = null;
  }
  if (streamElapsedTimer) { clearInterval(streamElapsedTimer); streamElapsedTimer = null; }
  currentAssistantDiv = null;
  currentContentDiv = null;
  currentRoleTrack = null;
  streamStartTime = null;
  activeTerminals = {};
}

function scrollToBottom() {
  if (!autoScrollEnabled) return;
  const cc = document.getElementById('chat-container');
  if (cc) cc.scrollTop = cc.scrollHeight;
}

// ── Tool terminal widget ────────────────────────────────────────────────────
function createTerminalWidget(ev) {
  if (!currentContentDiv) return;
  const id = ev.tool_id || ev.tool || Date.now();
  const w = document.createElement('div');
  w.className = 'tool-terminal'; w.dataset.tid = id;
  w.innerHTML = `<div class="tool-terminal-header" onclick="toggleTerminal(this)">
    <span class="term-status running"></span>
    <span class="term-name">&#x1F528; ${escapeHtml(ev.tool||'tool')}(${escapeHtml(JSON.stringify(ev.args||{}).slice(0,60))})</span>
    <span class="term-dur">0.0s</span>
  </div>
  <div class="tool-terminal-body">
    <span class="term-line stdin">&gt; ${escapeHtml(ev.tool||'')} ${escapeHtml(JSON.stringify(ev.args||{}))}</span>
  </div>
  <div class="tool-terminal-footer">
    <button class="sm-btn" onclick="copyTerminalOutput(this)">Copy output</button>
  </div>`;
  // Insert tool widget BEFORE the text segment so the final answer stays at the bottom
  const textSeg = currentContentDiv.querySelector('.msg-text-segment');
  if (textSeg) {
    currentContentDiv.insertBefore(w, textSeg);
  } else {
    currentContentDiv.appendChild(w);
  }
  activeTerminals[id] = {el: w, start: Date.now()};
  activeTerminals[id].timer = setInterval(() => {
    const durEl = w.querySelector('.term-dur');
    if (!durEl) return;
    durEl.textContent = ((Date.now() - activeTerminals[id].start) / 1000).toFixed(1) + 's';
  }, 120);
  scrollToBottom();
}

function finishTerminalWidget(ev) {
  const id = ev.tool_id || ev.tool;
  const entry = activeTerminals[id];
  if (!entry) return;
  const w = entry.el;
  const dur = ((Date.now() - entry.start) / 1000).toFixed(2) + 's';
  const status = w.querySelector('.term-status');
  const durEl = w.querySelector('.term-dur');
  const body = w.querySelector('.tool-terminal-body');
  if (entry.timer) clearInterval(entry.timer);
  status.classList.remove('running');
  const success = ev.success !== false;
  status.classList.add(success ? 'done' : 'err');
  durEl.textContent = dur;
  const out = ev.output !== undefined ? String(ev.output).slice(0, 6000) : '';
  const cls = success ? 'stdout' : 'stderr';
  out.split('\n').slice(0,50).forEach(line => {
    const s = document.createElement('span');
    s.className = 'term-line ' + cls;
    s.textContent = line;
    body.appendChild(s);
  });
  delete activeTerminals[id];
  scrollToBottom();
}

function setReasoningProgress(percent, label) {
  if (!currentProgressEl || !currentProgressFill) return;
  const clamped = Math.max(0, Math.min(100, Number(percent || 0)));
  currentProgressEl.dataset.progress = String(clamped);
  currentProgressFill.style.width = clamped + '%';
  const labelEl = currentProgressEl.querySelector('.reasoning-progress-label');
  if (labelEl && label) labelEl.textContent = label;
}

function bumpReasoningProgress(delta, label) {
  const cur = Number(currentProgressEl?.dataset.progress || 0);
  const next = Math.min(96, cur + Number(delta || 0));
  setReasoningProgress(next, label);
}

function toggleTerminal(header) {
  const body = header.parentElement?.querySelector('.tool-terminal-body');
  if (body) body.classList.toggle('collapsed');
}

function copyTerminalOutput(btn) {
  const body = btn.closest('.tool-terminal')?.querySelector('.tool-terminal-body');
  if (body) copyToClipboard(body.innerText);
}

// ── Provider / Status ──────────────────────────────────────────────────────
// Models: string = no price info, {v,l} = {api value, display label}
const MODELS = {
  copilot: [
    {v:'gpt-4.1',             l:'gpt-4.1  included'},
    {v:'gpt-4o',              l:'gpt-4o  included'},
    {v:'gpt-5-mini',          l:'gpt-5-mini  included'},
    {v:'claude-haiku-4.5',    l:'claude-haiku-4.5  0.33x'},
    {v:'claude-sonnet-4.5',   l:'claude-sonnet-4.5  1x'},
    {v:'claude-sonnet-4.6',   l:'claude-sonnet-4.6  1x'},
    {v:'gpt-5.2',             l:'gpt-5.2  1x'},
    {v:'gpt-5.3-codex',       l:'gpt-5.3-codex  1x'},
  ],
  grok: [
    {v:'grok-4.20',                    l:'grok-4.20  $2/$6'},
    {v:'grok-4.20-0309-reasoning',     l:'grok-4.20-reasoning  $2/$6'},
    {v:'grok-4.20-0309-non-reasoning', l:'grok-4.20-non-reasoning  $2/$6'},
    {v:'grok-4.20-multi-agent-0309',   l:'grok-4.20-multi-agent  $2/$6'},
    {v:'grok-4',                       l:'grok-4  $3/$15'},
    {v:'grok-4-fast',                  l:'grok-4-fast  $0.20/$0.50'},
    {v:'grok-4-1-fast-reasoning',      l:'grok-4-1-fast-reasoning  $0.20/$0.50'},
    {v:'grok-4-1-fast-non-reasoning',  l:'grok-4-1-fast-non-reasoning  $0.20/$0.50'},
    {v:'grok-3',                       l:'grok-3  $3/$15'},
    {v:'grok-3-fast',                  l:'grok-3-fast  $3/$15'},
    {v:'grok-3-mini',                  l:'grok-3-mini  $0.30/$0.50'},
    {v:'grok-3-mini-fast',             l:'grok-3-mini-fast  $0.30/$0.50'},
    {v:'grok-2-1212',                  l:'grok-2-1212  $2/$10'},
    {v:'grok-2-vision-1212',           l:'grok-2-vision-1212  $2/$10'},
    {v:'grok-vision-beta',             l:'grok-vision-beta'},
    {v:'grok-beta',                    l:'grok-beta'},
  ],
};

// Render <option> tags for a model array (strings or {v,l} objects)
function modelOpts(arr) {
  return (arr || []).map(m =>
    typeof m === 'object'
      ? `<option value="${m.v}">${m.l}</option>`
      : `<option value="${m}">${m}</option>`
  ).join('');
}

async function onModelChange() {
  const prov = document.getElementById('provider-select')?.value;
  const model = document.getElementById('model-select')?.value;
  if (!prov || !model) return;
  try {
    await fetch('/api/model', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({provider: prov, model: model})});
  } catch(e) {}
}

async function onProviderChange() {
  const prov = document.getElementById('provider-select')?.value;
  const modelSel = document.getElementById('model-select');
  const keyGrp = document.getElementById('api-key-group');
  const keyInput = document.getElementById('api-key-input');
  const budgetCard = document.getElementById('copilot-budget-card');
  if (modelSel) {
    modelSel.innerHTML = modelOpts(MODELS[prov]);
  }
  if (keyGrp) keyGrp.style.display = (prov === 'copilot') ? 'none' : 'flex';
  if (budgetCard) budgetCard.style.display = prov === 'copilot' ? 'flex' : 'none';
  if (keyInput) {
    keyInput.placeholder = prov === 'copilot'
      ? 'Optional GitHub token override'
      : 'API Key...';
  }
  // Switch provider on server side
  try {
    await fetch('/api/provider', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({provider: prov})});
  } catch(e) {}
  loadStatus();
}

async function loadStatus() {
  try {
    const r = await fetch('/api/status');
    const d = await r.json();
    const providerInfo = d.provider || {};
    const routerInfo = d.router || {};
    const budget = d.copilot_budget || null;
    const currentProvider = d.default_provider || providerInfo.key || inferProviderKey(providerInfo.name) || document.getElementById('provider-select')?.value || 'grok';
    const currentModel = d.current_model || providerInfo.model || '';
    const connected = typeof d.connected === 'boolean' ? d.connected : !!providerInfo.connected;
    const dot = document.getElementById('connection-dot');
    if (dot) { dot.className = 'connection-dot' + (connected ? ' connected' : ''); }
    // Set provider dropdown to whatever the server is using
    if (currentProvider) {
      const sel = document.getElementById('provider-select');
      if (sel && sel.value !== currentProvider) {
        sel.value = currentProvider;
        const modelSel = document.getElementById('model-select');
        if (modelSel) modelSel.innerHTML = modelOpts(MODELS[currentProvider]);
        const keyGrp = document.getElementById('api-key-group');
        const keyInput = document.getElementById('api-key-input');
        if (keyGrp) keyGrp.style.display = (currentProvider === 'copilot') ? 'none' : 'flex';
        if (keyInput) {
          keyInput.placeholder = currentProvider === 'copilot'
            ? 'Optional GitHub token override'
            : 'API Key...';
        }
      }
      // Set saved model
      if (currentModel) {
        const modelSel = document.getElementById('model-select');
        if (modelSel) modelSel.value = currentModel;
      }
    }
    updateCopilotBudgetCard(budget, currentProvider, currentModel);
    const badge = document.querySelector('.router-badge');
    const enabled = typeof d.router_enabled === 'boolean' ? d.router_enabled : !!routerInfo.enabled;
    if (badge) {
      badge.textContent = enabled ? 'on' : 'off';
      badge.classList.toggle('on', enabled);
      badge.classList.toggle('off', !enabled);
    }
    const txt = document.getElementById('router-status-text');
    if (txt) txt.textContent = enabled ? 'Enabled' : 'Disabled';
  } catch(e) {}
}

function inferProviderKey(name) {
  const text = String(name || '').toLowerCase();
  if (text.includes('copilot')) return 'copilot';
  if (text.includes('grok')) return 'grok';
  return '';
}

function updateCopilotBudgetCard(budget, provider, model) {
  const card = document.getElementById('copilot-budget-card');
  if (!card) return;
  const shouldShow = provider === 'copilot' && !!budget;
  card.style.display = shouldShow ? 'flex' : 'none';
  if (!shouldShow) return;

  const total = Number(budget.monthly_premium_requests || 0);
  const remaining = Number(budget.remaining ?? total);
  const used = Math.max(0, total - remaining);
  const pct = total > 0 ? Math.max(0, Math.min(100, (remaining / total) * 100)) : 0;
  const threshold = Number(budget.phase2_remaining_threshold || 60);
  const phase1 = budget.phase1_model || 'claude-sonnet-4.5';
  const phase2 = budget.phase2_model || 'claude-haiku-4.5';
  const fallback = Array.isArray(budget.fallback_models) && budget.fallback_models.length ? budget.fallback_models[0] : 'gpt-4.1';
  let stage = `Phase 1 · ${phase1}`;
  if (remaining <= 0) stage = `Fallback · ${fallback}`;
  else if (remaining <= threshold) stage = `Phase 2 · ${phase2}`;
  if (model) stage += ` · active: ${model}`;

  const planEl = document.getElementById('copilot-budget-plan');
  const stageEl = document.getElementById('copilot-budget-stage');
  const remEl = document.getElementById('copilot-budget-remaining');
  const usedEl = document.getElementById('copilot-budget-used');
  const fillEl = document.getElementById('copilot-budget-bar-fill');
  if (planEl) planEl.textContent = String(budget.plan || 'pro');
  if (stageEl) stageEl.textContent = stage;
  if (remEl) remEl.textContent = `${formatQuotaNumber(remaining)} remaining`;
  if (usedEl) usedEl.textContent = `${formatQuotaNumber(used)} used`;
  if (fillEl) fillEl.style.width = `${pct}%`;
}

function formatQuotaNumber(value) {
  return Number.isInteger(value) ? String(value) : value.toFixed(2).replace(/\.00$/, '');
}

async function setApiKey() {
  const key = document.getElementById('api-key-input')?.value?.trim();
  const prov = document.getElementById('provider-select')?.value;
  if (!key || !prov) { alert('Enter an API key first'); return; }
  try {
    const r = await fetch('/api/setkey', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({provider: prov, key})});
    const d = await r.json();
    if (d.connected) {
      const dot = document.getElementById('connection-dot');
      if (dot) dot.className = 'connection-dot connected';
    }
    // Collapse the provider settings panel after saving
    const body = document.getElementById('settings-body-provider');
    const chev = document.getElementById('chevron-provider');
    if (body) body.style.display = 'none';
    if (chev) chev.classList.remove('open');
    loadStatus();
  } catch(e) { console.error('setApiKey error', e); }
}

// ── Router ──────────────────────────────────────────────────────────────────
async function loadRouterStatus() {
  try {
    const r = await fetch('/api/status');
    const d = await r.json();
    const enabled = typeof d.router_enabled === 'boolean' ? d.router_enabled : !!(d.router && d.router.enabled);
    const tog = document.getElementById('router-toggle');
    if (tog) tog.checked = enabled;
    const badge = document.querySelector('.router-badge');
    if (badge) {
      badge.textContent = enabled ? 'on' : 'off';
      badge.classList.toggle('on', enabled);
      badge.classList.toggle('off', !enabled);
    }
    const txt = document.getElementById('router-status-text');
    if (txt) txt.textContent = enabled ? 'Enabled' : 'Disabled';
  } catch(e) {
    const txt = document.getElementById('router-status-text');
    if (txt) txt.textContent = 'Unavailable';
  }
}

async function setRouter(enabled) {
  try {
    await fetch('/api/router/toggle', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({enabled})});
    loadRouterStatus();
  } catch(e) {}
}

function toggleRouterStats() {
  const panel = document.getElementById('router-stats-panel');
  if (!panel) return;
  const open = panel.style.display === 'block';
  if (!open) {
    fetch('/api/router/stats').then(r=>r.json()).then(d => {
      panel.innerHTML = Object.entries(d).map(([k,v]) => `<div class="sys-row"><span>${escapeHtml(k)}</span><span>${typeof v === 'object' ? JSON.stringify(v) : v}</span></div>`).join('');
      panel.style.display = 'block';
    }).catch(()=>{});
  } else { panel.style.display = 'none'; }
}

// ── Monitor ─────────────────────────────────────────────────────────────────
let monitorInterval = null;

const STAT_LABELS = {
  cpu: 'CPU', cpu_cores: 'CPU Cores', ram: 'RAM', disk: 'Disk',
  net_upload: '↑ Upload', net_download: '↓ Download', uptime: 'Uptime',
  gpu_name: 'GPU', gpu_util: 'GPU Usage', gpu_mem: 'GPU Mem', gpu_temp: 'GPU Temp',
  gpu0_name: 'GPU 0', gpu0_util: 'GPU 0 Usage', gpu0_mem: 'GPU 0 Mem', gpu0_temp: 'GPU 0 Temp',
  gpu1_name: 'GPU 1', gpu1_util: 'GPU 1 Usage', gpu1_mem: 'GPU 1 Mem', gpu1_temp: 'GPU 1 Temp',
};

async function startMonitor() {
  try {
    await fetch('/api/monitor/start', {method:'POST'});
    const badge = document.getElementById('monitor-badge');
    if (badge) { badge.textContent = 'on'; badge.classList.add('on'); badge.classList.remove('off'); }
    clearInterval(monitorInterval);
    monitorInterval = setInterval(updateMonitor, 3000);
    updateMonitor();
  } catch(e) {}
}
async function stopMonitor() {
  try {
    await fetch('/api/monitor/stop', {method:'POST'});
    const badge = document.getElementById('monitor-badge');
    if (badge) { badge.textContent = 'off'; badge.classList.add('off'); badge.classList.remove('on'); }
    clearInterval(monitorInterval);
    monitorInterval = null;
  } catch(e) {}
}
async function updateMonitor() {
  try {
    const r = await fetch('/api/monitor/stats');
    const d = await r.json();
    const grid = document.getElementById('sys-grid');
    if (!grid) return;
    const sys = d.system || {};
    if (Object.keys(sys).length === 0) {
      grid.innerHTML = '<div class="sys-row muted"><span>No data yet</span></div>';
    } else {
      grid.innerHTML = Object.entries(sys).map(([k, v]) => {
        const label = STAT_LABELS[k] || k.replace(/_/g, ' ');
        return `<div class="sys-row"><span>${escapeHtml(label)}</span><span>${escapeHtml(String(v))}</span></div>`;
      }).join('');
    }
    const alertList = document.getElementById('alert-list');
    if (alertList) {
      const alerts = d.alerts || [];
      alertList.innerHTML = alerts.length
        ? alerts.slice(-5).reverse().map(a => `<div class="alert-item">${escapeHtml(a)}</div>`).join('')
        : '';
    }
    const badge = document.getElementById('monitor-badge');
    if (badge) {
      badge.textContent = d.running ? 'on' : 'off';
      badge.classList.toggle('on', !!d.running);
      badge.classList.toggle('off', !d.running);
    }
  } catch(e) {}
}

// ── Tools ────────────────────────────────────────────────────────────────────
async function loadTools() {
  try {
    const r = await fetch('/api/tools');
    const d = await r.json();
    const list = document.getElementById('tool-list');
    const countBadge = document.getElementById('tool-count');
    const tools = d.tools || [];
    if (countBadge) countBadge.textContent = tools.length;
    if (list) list.innerHTML = tools.map(t =>
      `<div class="tool-item"><span class="tool-item-name">${escapeHtml(t.name)}</span><span class="badge">${escapeHtml(t.type||'tool')}</span></div>`
    ).join('');
  } catch(e) {}
}

let _generatedToolSpec = null;

function openToolModal() {
  _generatedToolSpec = null;
  document.getElementById('tool-modal').style.display = 'flex';
  document.getElementById('tool-step-describe').style.display = '';
  document.getElementById('tool-step-preview').style.display = 'none';
  document.getElementById('tool-generate-error').style.display = 'none';
  document.getElementById('btn-tool-generate').style.display = '';
  document.getElementById('btn-tool-save').style.display = 'none';
  document.getElementById('btn-tool-back').style.display = 'none';
  document.getElementById('tool-modal-title').textContent = 'Create Tool with AI';
  document.getElementById('tool-prompt').value = '';
  document.getElementById('tool-prompt').focus();
}

function closeToolModal() {
  document.getElementById('tool-modal').style.display = 'none';
}

function toolGoBack() {
  document.getElementById('tool-step-describe').style.display = '';
  document.getElementById('tool-step-preview').style.display = 'none';
  document.getElementById('btn-tool-generate').style.display = '';
  document.getElementById('btn-tool-save').style.display = 'none';
  document.getElementById('btn-tool-back').style.display = 'none';
  document.getElementById('tool-modal-title').textContent = 'Create Tool with AI';
}

async function generateTool() {
  const prompt = document.getElementById('tool-prompt')?.value?.trim();
  if (!prompt) { alert('Describe the tool first'); return; }
  const btn = document.getElementById('btn-tool-generate');
  const errEl = document.getElementById('tool-generate-error');
  errEl.style.display = 'none';
  btn.textContent = 'Generating…';
  btn.disabled = true;
  try {
    const r = await fetch('/api/tools/generate', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({description: prompt})
    });
    const d = await r.json();
    if (!d.success) throw new Error(d.message || 'Generation failed');
    _generatedToolSpec = d.spec;
    document.getElementById('tool-preview-name').value = d.spec.name || '';
    document.getElementById('tool-preview-desc').value = d.spec.description || '';
    document.getElementById('tool-preview-code').value = d.spec.code || '';
    document.getElementById('tool-step-describe').style.display = 'none';
    document.getElementById('tool-step-preview').style.display = '';
    document.getElementById('btn-tool-generate').style.display = 'none';
    document.getElementById('btn-tool-save').style.display = '';
    document.getElementById('btn-tool-back').style.display = '';
    document.getElementById('tool-modal-title').textContent = 'Review & Save';
  } catch(e) {
    errEl.textContent = e.message;
    errEl.style.display = 'block';
  } finally {
    btn.textContent = 'Generate ✦';
    btn.disabled = false;
  }
}

async function saveGeneratedTool() {
  const name = document.getElementById('tool-preview-name')?.value?.trim();
  const desc = document.getElementById('tool-preview-desc')?.value?.trim();
  const code = document.getElementById('tool-preview-code')?.value?.trim();
  const args = _generatedToolSpec?.args || [];
  if (!name || !code) { alert('Name and code are required'); return; }
  const errBox = document.getElementById('tool-create-error');
  errBox.style.display = 'none';
  try {
    const r = await fetch('/api/tools/create', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name, description: desc, args, code})
    });
    const d = await r.json();
    if (!d.success) throw new Error(d.message || 'Save failed');
    closeToolModal();
    loadTools();
  } catch(e) {
    errBox.querySelector('.tool-error-msg').textContent = e.message;
    errBox.style.display = 'block';
  }
}

// ── Markdown renderer ────────────────────────────────────────────────────────
function renderMarkdown(text) {
  if (!text) return '';
  let html = escapeHtml(text);
  // code blocks
  html = html.replace(/```([\s\S]*?)```/g, (_,c)=>`<pre><code>${c}</code></pre>`);
  // inline code
  html = html.replace(/`([^`]+)`/g, (_,c)=>`<code>${c}</code>`);
  // bold
  html = html.replace(/\*\*([^*]+)\*\*/g, (_,t)=>`<strong>${t}</strong>`);
  // italic
  html = html.replace(/\*([^*]+)\*/g, (_,t)=>`<em>${t}</em>`);
  // headers
  html = html.replace(/^### (.+)$/gm, (_,t)=>`<h3>${t}</h3>`);
  html = html.replace(/^## (.+)$/gm, (_,t)=>`<h2>${t}</h2>`);
  html = html.replace(/^# (.+)$/gm, (_,t)=>`<h1>${t}</h1>`);
  // bullets
  html = html.replace(/^\* (.+)$/gm, (_,t)=>`<li>${t}</li>`);
  html = html.replace(/(<li>.*<\/li>\n?)+/g, m=>`<ul>${m}</ul>`);
  // numbered list
  html = html.replace(/^\d+\. (.+)$/gm, (_,t)=>`<li>${t}</li>`);
  // blockquote
  html = html.replace(/^&gt; (.+)$/gm, (_,t)=>`<blockquote>${t}</blockquote>`);
  // paragraphs
  html = html.replace(/\n\n/g, '</p><p>');
  html = html.replace(/\n/g, '<br>');
  return '<p>' + html + '</p>';
}

// ── Utilities ────────────────────────────────────────────────────────────────
function escapeHtml(s) {
  if (s == null) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function copyToClipboard(text) {
  navigator.clipboard.writeText(text).catch(()=>{
    const ta = document.createElement('textarea');
    ta.value = text; document.body.appendChild(ta); ta.select();
    document.execCommand('copy'); document.body.removeChild(ta);
  });
}
function copyMessageText(btn) {
  const bubble = btn.closest('.msg-bubble');
  const seg = bubble?.querySelector('.msg-text-segment');
  if (seg) copyToClipboard(seg.innerText);
}
function resizeTextarea(el) {
  el.style.height='auto';
  el.style.height = Math.min(el.scrollHeight, 200) + 'px';
}
function setupTextarea() {
  const ta = document.getElementById('user-input');
  if (!ta) return;
  ta.addEventListener('input', () => resizeTextarea(ta));
  ta.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  });
}

// ── Power ─────────────────────────────────────────────────────────────────
let pendingPowerAction = null;
let pendingPowerTimer = null;

function resetPowerConfirmation() {
  if (pendingPowerTimer) { clearTimeout(pendingPowerTimer); pendingPowerTimer = null; }
  pendingPowerAction = null;
  const rb = document.getElementById('btn-restart');
  const sb = document.getElementById('btn-shutdown');
  if (rb) { rb.classList.remove('confirm'); rb.innerHTML = '&#x21BA; Restart'; rb.title = 'Restart server'; }
  if (sb) { sb.classList.remove('confirm'); sb.innerHTML = '&#x23FB; Shutdown'; sb.title = 'Shutdown server'; }
}

async function shutdownServer() {
  if (pendingPowerAction === 'shutdown') {
    resetPowerConfirmation();
    try {
      await fetch('/api/shutdown', {method:'POST'});
      document.body.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100vh;background:#111;color:#e8e8e8;font-family:sans-serif;flex-direction:column;gap:12px"><span style="font-size:36px">⏻</span><p>Server shut down.</p></div>';
    } catch(e) {}
    return;
  }
  resetPowerConfirmation();
  pendingPowerAction = 'shutdown';
  const btn = document.getElementById('btn-shutdown');
  if (btn) { btn.classList.add('confirm'); btn.textContent = 'Confirm shutdown'; btn.title = 'Click again to shut down'; }
  pendingPowerTimer = setTimeout(resetPowerConfirmation, 3000);
}

async function restartServer() {
  if (pendingPowerAction === 'restart') {
    resetPowerConfirmation();
    try {
      await fetch('/api/restart', {method:'POST'});
      document.body.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100vh;background:#111;color:#e8e8e8;font-family:sans-serif;flex-direction:column;gap:12px"><span style="font-size:36px">↺</span><p>Restarting… page will reload in 3s</p></div>';
      setTimeout(() => location.reload(), 3000);
    } catch(e) {}
    return;
  }
  resetPowerConfirmation();
  pendingPowerAction = 'restart';
  const btn = document.getElementById('btn-restart');
  if (btn) { btn.classList.add('confirm'); btn.textContent = 'Confirm restart'; btn.title = 'Click again to restart'; }
  pendingPowerTimer = setTimeout(resetPowerConfirmation, 3000);
}

// ── Memory panel ────────────────────────────────────────────────────────────
let currentMemTab = 'episodes';
let memData = null;

async function loadMemory() {
  const badge = document.getElementById('memory-badge');
  if (badge) badge.textContent = '…';
  try {
    const r = await fetch('/api/memory');
    memData = await r.json();
    const totalEp = memData.episodic?.count || 0;
    const totalFacts = memData.facts?.global_count || 0;
    if (badge) badge.textContent = totalEp + 'ep · ' + totalFacts + 'f';
    renderMemTab(currentMemTab);
  } catch(e) {
    if (badge) badge.textContent = 'err';
  }
}

function switchMemTab(tab) {
  currentMemTab = tab;
  document.querySelectorAll('.mem-tab').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
  ['episodes','facts','strategy','session'].forEach(t => {
    const p = document.getElementById('mem-panel-' + t);
    if (p) p.style.display = t === tab ? 'flex' : 'none';
  });
  renderMemTab(tab);
}

function renderMemTab(tab) {
  if (!memData) return;
  if (tab === 'episodes') renderEpisodes();
  else if (tab === 'facts') renderFacts();
  else if (tab === 'strategy') renderStrategy();
  else if (tab === 'session') renderSession();
}

function renderEpisodes() {
  const panel = document.getElementById('mem-panel-episodes');
  if (!panel) return;
  const episodes = memData.episodic?.episodes || [];
  if (!episodes.length) { panel.innerHTML = '<div class="mem-empty">No episodes recorded yet</div>'; return; }
  panel.innerHTML = episodes.map(ep => {
    const qPct = Math.round((ep.quality_score || 0) * 100);
    const qColor = qPct >= 70 ? 'var(--green)' : qPct >= 40 ? 'var(--yellow)' : 'var(--red)';
    const ts = ep.timestamp ? new Date(ep.timestamp).toLocaleString() : '';
    const tools = (ep.tools_used || []).slice(0,4).join(', ') || '—';
    const lessons = (ep.lessons || []).join(' · ');
    return `<div class="mem-episode">
      <div class="mem-episode-head">
        <span class="mem-outcome ${ep.outcome || 'partial'}">${ep.outcome || '?'}</span>
        <span style="font-family:var(--mono);color:var(--accent2)">${escapeHtml(ep.task_type || '')}</span>
        <span style="color:var(--text3);margin-left:auto">${escapeHtml(ts)}</span>
      </div>
      <div class="mem-episode-summary">${escapeHtml(ep.task_summary || '')}</div>
      <div class="mem-episode-meta">${escapeHtml(ep.strategy || '')} · ${escapeHtml(ep.provider_model || '')} · tools: ${escapeHtml(tools)}</div>
      <div class="mem-quality-bar"><div class="mem-quality-fill" style="width:${qPct}%;background:${qColor}"></div></div>
      ${lessons ? `<div class="mem-episode-lessons">${escapeHtml(lessons)}</div>` : ''}
    </div>`;
  }).join('');
}

function renderFacts() {
  const panel = document.getElementById('mem-panel-facts');
  if (!panel) return;
  const global = memData.facts?.global || [];
  const eng = memData.facts?.engagement || [];
  if (!global.length && !eng.length) { panel.innerHTML = '<div class="mem-empty">No facts stored yet</div>'; return; }
  let html = '';
  if (eng.length) {
    html += '<div class="mem-section-label">Session facts</div>';
    html += eng.map(f => factCard(f, false)).join('');
  }
  if (global.length) {
    html += '<div class="mem-section-label">Global facts</div>';
    html += global.map(f => factCard(f, true)).join('');
  }
  panel.innerHTML = html;
}

function factCard(f, deletable) {
  const confPct = Math.round((f.confidence || 0) * 100);
  const del = deletable
    ? `<button class="mem-fact-del" onclick="forgetFact('${escapeHtml(f.subject)}','${escapeHtml(f.predicate)}')" title="Forget this fact">✕</button>`
    : '';
  return `<div class="mem-fact">
    <div class="mem-fact-body">
      <div class="mem-fact-key">${escapeHtml(f.subject)} → ${escapeHtml(f.predicate)}</div>
      <div class="mem-fact-val">${escapeHtml(f.value)}</div>
      <div class="mem-fact-meta">
        <span class="mem-fact-conf"><span class="mem-fact-conf-fill" style="width:${confPct}%"></span></span>
        ${confPct}% · ${escapeHtml(f.source || 'agent')}
      </div>
    </div>
    ${del}
  </div>`;
}

async function forgetFact(subject, predicate) {
  try {
    await fetch('/api/memory/facts', {method:'DELETE', headers:{'Content-Type':'application/json'}, body: JSON.stringify({subject, predicate})});
    await loadMemory();
  } catch(e) {}
}

function renderStrategy() {
  const panel = document.getElementById('mem-panel-strategy');
  if (!panel) return;
  const scores = memData.strategy?.scores || {};
  const taskTypes = Object.keys(scores);
  if (!taskTypes.length) { panel.innerHTML = '<div class="mem-empty">No strategy data yet</div>'; return; }
  panel.innerHTML = taskTypes.map(tt => {
    const strategies = scores[tt];
    const sorted = Object.entries(strategies).sort((a,b) => b[1].quality - a[1].quality);
    const best = sorted[0];
    return `<div class="mem-strategy-row">
      <div class="mem-strategy-head">
        <span class="mem-strategy-type">${escapeHtml(tt)}</span>
        <span class="mem-strategy-badge">best: ${escapeHtml(best[0])}</span>
      </div>
      ${sorted.map(([strat, val]) => {
        const pct = Math.round((val.quality || 0) * 100);
        const topTools = _topFreqTools(val.tools_freq || {}, 3);
        return `<div style="margin-top:4px">
          <div style="display:flex;justify-content:space-between;font-size:10px;color:var(--text2)">
            <span>${escapeHtml(strat)} <span style="color:var(--text3)">×${val.n}</span></span>
            <span>${pct}%</span>
          </div>
          <div class="mem-strategy-bar"><div class="mem-strategy-fill" style="width:${pct}%"></div></div>
          ${topTools ? `<div class="mem-strategy-tools">tools: ${escapeHtml(topTools)}</div>` : ''}
        </div>`;
      }).join('')}
    </div>`;
  }).join('');
}

function _topFreqTools(freq, n) {
  return Object.entries(freq).sort((a,b)=>b[1]-a[1]).slice(0,n).map(e=>e[0]).join(', ');
}

function renderSession() {
  const panel = document.getElementById('mem-panel-session');
  if (!panel) return;
  const s = memData.session;
  if (!s) { panel.innerHTML = '<div class="mem-empty">No active session</div>'; return; }
  const sections = [
    {label:'In-flight tasks', key:'in_flight'},
    {label:'Findings', key:'findings'},
    {label:'Raw recon', key:'raw_recon'},
    {label:'Patterns', key:'patterns'},
  ];
  let html = `<div class="mem-session-block" style="margin-bottom:5px">
    <div class="mem-session-title">Session: ${escapeHtml(s.title || s.conversation_id || '')}</div>
    <div style="font-size:10px;color:var(--text3)">Started: ${s.started_at ? new Date(s.started_at).toLocaleTimeString() : '?'}</div>
  </div>`;
  sections.forEach(({label, key}) => {
    const items = s[key] || [];
    if (!items.length) return;
    html += `<div class="mem-session-block">
      <div class="mem-session-title">${label} (${items.length})</div>
      ${items.slice(-10).map(i => `<div class="mem-session-item">${escapeHtml(String(i).slice(0,200))}</div>`).join('')}
    </div>`;
  });
  panel.innerHTML = html || '<div class="mem-empty">No session data</div>';
}
