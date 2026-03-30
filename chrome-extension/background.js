const API_BASE_KEY = "agentNimiApiBase";
const DEFAULT_API_BASE = "http://127.0.0.1:1337";
const CONTEXT_TTL_MS = 4 * 60 * 1000;
const DEDUPE_WINDOW_MS = 3000;

const lastContextByTab = new Map();

async function getApiBase() {
  const data = await chrome.storage.local.get(API_BASE_KEY);
  return String(data[API_BASE_KEY] || DEFAULT_API_BASE).replace(/\/+$/, "");
}

function stableHash(input) {
  let hash = 0;
  const text = String(input || "");
  for (let i = 0; i < text.length; i += 1) {
    hash = ((hash << 5) - hash) + text.charCodeAt(i);
    hash |= 0;
  }
  return String(hash);
}

function shouldSyncContext(tabId, payload) {
  const key = String(tabId);
  const now = Date.now();
  const hash = stableHash(JSON.stringify({
    title: payload.title || "",
    url: payload.url || "",
    text: payload.text || "",
    snippets: payload.snippets || []
  }));
  const prev = lastContextByTab.get(key);
  if (prev && prev.hash === hash && (now - prev.ts) < DEDUPE_WINDOW_MS) {
    return false;
  }
  lastContextByTab.set(key, { hash, ts: now, payload });
  return true;
}

async function pushContext(tabId, payload) {
  if (!shouldSyncContext(tabId, payload)) {
    return { ok: true, deduped: true };
  }
  const apiBase = await getApiBase();
  const res = await fetch(`${apiBase}/api/extension/context`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      tab_key: String(tabId),
      title: payload.title || "",
      url: payload.url || "",
      text: payload.text || "",
      snippets: payload.snippets || [],
      forms: payload.forms || [],
      links: payload.links || []
    })
  });
  if (!res.ok) {
    throw new Error(`Context sync failed (${res.status})`);
  }
  return await res.json();
}

function askTabForContext(tabId) {
  chrome.tabs.sendMessage(tabId, { type: "collect_context" }, () => {
    void chrome.runtime.lastError;
  });
}

// ─── Execute browser action on the active tab ─────────────────────────────────

async function executeBrowserAction(tabId, action) {
  const [result] = await chrome.scripting.executeScript({
    target: { tabId },
    func: (action) => {
      return new Promise((resolve) => {
        chrome.runtime.sendMessage({ type: "browser_action", ...action }, (resp) => {
          resolve(resp || { ok: false, error: "No response" });
        });
      });
    },
    args: [action]
  });
  return result?.result || { ok: false };
}

// ─── Lifecycle ────────────────────────────────────────────────────────────────

chrome.runtime.onInstalled.addListener(async () => {
  await chrome.storage.local.set({ [API_BASE_KEY]: DEFAULT_API_BASE });
});

chrome.action.onClicked.addListener(async (tab) => {
  if (!tab?.id) return;
  await chrome.sidePanel.open({ tabId: tab.id });
});

// Sync context on ALL tab updates (not just TDXArena)
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (!tab?.url || tab.url.startsWith("chrome://") || tab.url.startsWith("chrome-extension://")) return;
  if (changeInfo.status === "complete") {
    askTabForContext(tabId);
  }
});

chrome.tabs.onActivated.addListener(async ({ tabId }) => {
  const tab = await chrome.tabs.get(tabId);
  if (tab?.url && !tab.url.startsWith("chrome://") && !tab.url.startsWith("chrome-extension://")) {
    askTabForContext(tabId);
  }
});

// ─── Message Router ───────────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg || !msg.type) return false;

  if (msg.type === "page_context") {
    const tabId = sender.tab?.id;
    if (!tabId) {
      sendResponse({ ok: false, error: "No tab id" });
      return false;
    }
    pushContext(tabId, msg.payload || {})
      .then((data) => sendResponse({ ok: true, data }))
      .catch((err) => sendResponse({ ok: false, error: String(err.message || err) }));
    return true;
  }

  if (msg.type === "companion_health") {
    getApiBase()
      .then(async (apiBase) => {
        const res = await fetch(`${apiBase}/api/extension/health`);
        const data = await res.json();
        sendResponse({ ok: res.ok, data, apiBase });
      })
      .catch((err) => sendResponse({ ok: false, error: String(err.message || err) }));
    return true;
  }

  if (msg.type === "companion_stream_chat") {
    const tabId = msg.tabId;
    const text = String(msg.message || "").trim();
    const conversationId = String(msg.conversationId || "").trim();
    if (!text) {
      sendResponse({ ok: false, error: "Empty message" });
      return false;
    }
    getApiBase()
      .then(async (apiBase) => {
        // Build page-context block from cached tab context and prepend to message.
        const ctxInfo = lastContextByTab.get(String(tabId || ""));
        let fullMessage = text;
        if (ctxInfo && ctxInfo.payload && (Date.now() - ctxInfo.ts) < CONTEXT_TTL_MS) {
          const c = ctxInfo.payload;
          const domain = c.url ? c.url.replace(/https?:\/\//, "").split("/")[0] : "";
          const snippets = (c.snippets || []).slice(0, 6).map(s => `- ${String(s).slice(0, 200)}`).join("\n");
          const links = (c.links || []).slice(0, 10).map(l => `- [${l.text || ""}](${l.href || ""})`).join("\n");
          const ctxBlock = [
            "[PAGE CONTEXT]",
            `ACTIVE_PAGE_URL: ${c.url || ""}`,
            `ACTIVE_PAGE_DOMAIN: ${domain}`,
            `Title: ${c.title || ""}`,
            "NOTE: When the user says 'this site', 'this page', or 'here', they mean ACTIVE_PAGE_DOMAIN above.",
            "",
            `MainText:\n${String(c.text || "").slice(0, 6000)}`,
            snippets ? `\nCode Snippets:\n${snippets}` : "",
            links ? `\nLinks:\n${links}` : "",
          ].filter(Boolean).join("\n");
          fullMessage = `${ctxBlock}\n\n${text}`;
        }

        // Send directly to /api/chat — same pipeline as the web UI.
        // The web UI will show the full live conversation automatically.
        // display_message is the original clean text; message has the page context prepended.
        const res = await fetch(`${apiBase}/api/chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            message: fullMessage,
            display_message: text,
            conversation_id: conversationId || undefined,
            mode: "agent"
          })
        });
        if (!res.ok || !res.body) {
          const textBody = await res.text();
          sendResponse({ ok: false, error: textBody || `HTTP ${res.status}` });
          return;
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buf = "";
        const emitDataLines = (text) => {
          const lines = String(text || "").split("\n");
          for (const line of lines) {
            if (!line.startsWith("data: ")) continue;
            try {
              const ev = JSON.parse(line.slice(6));
              chrome.runtime.sendMessage({ type: "companion_stream_event", event: ev });
            } catch (_) {
              // ignore malformed line
            }
          }
        };
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          const lines = buf.split("\n");
          buf = lines.pop() || "";
          emitDataLines(lines.join("\n"));
        }
        // Flush decoder + parse any final buffered event line at EOF.
        buf += decoder.decode();
        if (buf.trim()) emitDataLines(buf);
        chrome.runtime.sendMessage({ type: "companion_stream_end" });
        sendResponse({ ok: true });
      })
      .catch((err) => sendResponse({ ok: false, error: String(err.message || err) }));
    return true;
  }

  if (msg.type === "set_api_base") {
    const apiBase = String(msg.apiBase || "").trim().replace(/\/+$/, "");
    chrome.storage.local.set({ [API_BASE_KEY]: apiBase || DEFAULT_API_BASE })
      .then(() => sendResponse({ ok: true }))
      .catch((err) => sendResponse({ ok: false, error: String(err.message || err) }));
    return true;
  }

  if (msg.type === "get_last_context") {
    const key = String(msg.tabId || "");
    const info = lastContextByTab.get(key);
    if (!info || (Date.now() - info.ts) > CONTEXT_TTL_MS) {
      sendResponse({ ok: true, context: null });
      return false;
    }
    sendResponse({ ok: true, context: info.payload, ts: info.ts });
    return false;
  }

  // ─── Browser action proxy ─────────────────────────────────────────────────
  if (msg.type === "do_browser_action") {
    chrome.tabs.query({ active: true, currentWindow: true }, async (tabs) => {
      const tabId = tabs[0]?.id;
      if (!tabId) { sendResponse({ ok: false, error: "No active tab" }); return; }
      try {
        const result = await executeBrowserAction(tabId, msg.action || {});
        sendResponse(result);
      } catch (err) {
        sendResponse({ ok: false, error: String(err.message || err) });
      }
    });
    return true;
  }

  return false;
});
