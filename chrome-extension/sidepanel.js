const messagesEl = document.getElementById("messages");
const inputEl = document.getElementById("input");
const sendBtn = document.getElementById("send");
const statusEl = document.getElementById("status");
const contextMetaEl = document.getElementById("context-meta");

let activeTabId = null;
let currentAssistantEl = null;
let streaming = false;
let pendingConvId = null;
let currentConvId = null;
const convIdByTab = new Map();
let streamedAnyText = false;

function appendStreamText(text) {
  if (!text) return;
  if (!currentAssistantEl) currentAssistantEl = appendMessage("assistant", "");
  currentAssistantEl.textContent += String(text);
  streamedAnyText = true;
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function appendMessage(role, text) {
  const el = document.createElement("div");
  el.className = `msg ${role}`;
  el.textContent = text;
  messagesEl.appendChild(el);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return el;
}

function updateStatus(text) {
  statusEl.textContent = text;
}

async function getActiveTab() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  return tabs[0] || null;
}

async function refreshContext() {
  const tab = await getActiveTab();
  if (!tab?.id) return;
  const prevTabId = activeTabId;
  activeTabId = tab.id;
  if (prevTabId !== activeTabId) {
    currentConvId = convIdByTab.get(String(activeTabId)) || null;
  }
  chrome.runtime.sendMessage({ type: "get_last_context", tabId: tab.id }, (resp) => {
    if (!resp?.ok || !resp.context) {
      contextMetaEl.textContent = "No context synced yet. Navigate to any page.";
      return;
    }
    const c = resp.context;
    const summary = `${c.title || "(untitled)"} | ${c.url || ""}`;
    contextMetaEl.textContent = summary.slice(0, 200);
  });
}

function onStreamEvent(ev) {
  const type = ev?.type || "";

  if (type === "conversation_id") {
    pendingConvId = ev.conversation_id;
    currentConvId = ev.conversation_id || currentConvId;
    if (activeTabId != null && currentConvId) {
      convIdByTab.set(String(activeTabId), currentConvId);
    }
    // Show live link immediately — user can watch full reasoning in the web UI
    // while the agent is still running tools.
    const existingLink = document.getElementById("conv-link");
    if (existingLink) existingLink.remove();
    const link = document.createElement("a");
    link.id = "conv-link";
    link.href = `http://127.0.0.1:1337/?conv=${pendingConvId}`;
    link.target = "_blank";
    link.textContent = "\u26A1 Watch live in AgentNimi \u2197";
    link.style.cssText = "display:block;margin:6px 8px;font-size:12px;color:#86efac;text-decoration:underline;font-weight:bold;";
    messagesEl.after(link);
    return;
  }

  if (type === "chunk" || type === "text_chunk") {
    appendStreamText(ev.content || ev.text || "");
    return;
  }
  if (type === "error") {
    if (!currentAssistantEl) currentAssistantEl = appendMessage("assistant", "");
    currentAssistantEl.textContent += `\n[error] ${ev.message || "unknown"}`;
    return;
  }
  if (type === "done") {
    // Fallback for providers that return a final-only payload.
    if (!streamedAnyText && ev.content) {
      appendStreamText(ev.content);
    }
    streaming = false;
    sendBtn.disabled = false;
    updateStatus("connected");
    currentAssistantEl = null;
    streamedAnyText = false;
    // Agent is done — turn the live link into a static "view session" link.
    const liveLink = document.getElementById("conv-link");
    if (liveLink) {
      liveLink.textContent = "\u2197 View full session in AgentNimi";
      liveLink.style.color = "#7dd3fc";
    }
    pendingConvId = null;
    return;
  }
}

chrome.runtime.onMessage.addListener((msg) => {
  if (msg?.type === "companion_stream_event") {
    onStreamEvent(msg.event || {});
  } else if (msg?.type === "companion_stream_end") {
    streaming = false;
    sendBtn.disabled = false;
    updateStatus("connected");
    currentAssistantEl = null;
    streamedAnyText = false;
  }
});

async function sendMessage() {
  const text = inputEl.value.trim();
  if (!text || streaming) return;
  if (!activeTabId) await refreshContext();
  appendMessage("user", text);
  inputEl.value = "";
  // Clear old conversation link and reset state for new message
  const oldLink = document.getElementById("conv-link");
  if (oldLink) oldLink.remove();
  pendingConvId = null;
  currentAssistantEl = appendMessage("assistant", "");
  streamedAnyText = false;
  streaming = true;
  sendBtn.disabled = true;
  updateStatus("streaming...");

  chrome.runtime.sendMessage(
    {
      type: "companion_stream_chat",
      tabId: activeTabId,
      message: text,
      conversationId: currentConvId || undefined
    },
    (resp) => {
      if (!resp?.ok) {
        currentAssistantEl.textContent = `[error] ${resp?.error || "failed to send"}`;
        streaming = false;
        sendBtn.disabled = false;
        updateStatus("error");
      }
    }
  );
}

async function boot() {
  chrome.runtime.sendMessage({ type: "companion_health" }, (resp) => {
    if (resp?.ok) {
      updateStatus(`connected (${resp.data?.provider || "agent"})`);
    } else {
      updateStatus("offline");
      appendMessage("assistant", "Could not connect to AgentNimi at localhost:1337.");
    }
  });
  await refreshContext();
}

sendBtn.addEventListener("click", sendMessage);
inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

boot();
