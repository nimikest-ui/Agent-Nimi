const messagesEl = document.getElementById("messages");
const inputEl = document.getElementById("input");
const sendBtn = document.getElementById("send");
const statusEl = document.getElementById("status");
const contextMetaEl = document.getElementById("context-meta");

let activeTabId = null;
let currentAssistantEl = null;
let streaming = false;

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
  activeTabId = tab.id;
  chrome.runtime.sendMessage({ type: "get_last_context", tabId: tab.id }, (resp) => {
    if (!resp?.ok || !resp.context) {
      contextMetaEl.textContent = "No synced context yet. Open a TDXArena challenge tab.";
      return;
    }
    const c = resp.context;
    const summary = `${c.title || "(untitled)"} | ${c.url || ""}`;
    contextMetaEl.textContent = summary.slice(0, 200);
  });
}

function onStreamEvent(ev) {
  const type = ev?.type || "";
  if (type === "chunk" || type === "text_chunk") {
    if (!currentAssistantEl) currentAssistantEl = appendMessage("assistant", "");
    currentAssistantEl.textContent += String(ev.content || ev.text || "");
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return;
  }
  if (type === "error") {
    if (!currentAssistantEl) currentAssistantEl = appendMessage("assistant", "");
    currentAssistantEl.textContent += `\n[error] ${ev.message || "unknown"}`;
    return;
  }
  if (type === "done") {
    streaming = false;
    sendBtn.disabled = false;
    updateStatus("connected");
    currentAssistantEl = null;
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
  }
});

async function sendMessage() {
  const text = inputEl.value.trim();
  if (!text || streaming) return;
  if (!activeTabId) await refreshContext();
  appendMessage("user", text);
  inputEl.value = "";
  currentAssistantEl = appendMessage("assistant", "");
  streaming = true;
  sendBtn.disabled = true;
  updateStatus("streaming...");

  chrome.runtime.sendMessage(
    { type: "companion_stream_chat", tabId: activeTabId, message: text },
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
