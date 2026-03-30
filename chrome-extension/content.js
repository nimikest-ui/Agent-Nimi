// ─── Context Collection ───────────────────────────────────────────────────────

function pickMainText() {
  const candidates = [
    "main",
    "[role='main']",
    ".challenge-content",
    ".content",
    ".problem",
    ".task",
    "article",
    ".markdown-body",
    "#content",
    "#main"
  ];
  for (const sel of candidates) {
    const el = document.querySelector(sel);
    if (el && el.innerText && el.innerText.trim().length > 60) {
      return el.innerText.trim();
    }
  }
  return (document.body?.innerText || "").trim();
}

function collectSnippets() {
  const out = [];
  const codeBlocks = Array.from(document.querySelectorAll("pre, code")).slice(0, 8);
  for (const el of codeBlocks) {
    const text = (el.innerText || "").trim();
    if (text) out.push(text.slice(0, 350));
  }
  return out;
}

function collectForms() {
  const forms = [];
  for (const form of Array.from(document.querySelectorAll("form")).slice(0, 5)) {
    const inputs = Array.from(form.querySelectorAll("input, select, textarea")).map(el => ({
      type: el.type || el.tagName.toLowerCase(),
      name: el.name || el.id || "",
      placeholder: el.placeholder || "",
      value: el.type === "password" ? "[hidden]" : (el.value || "")
    }));
    forms.push({ action: form.action || "", inputs });
  }
  return forms;
}

function collectLinks() {
  return Array.from(document.querySelectorAll("a[href]"))
    .slice(0, 20)
    .map(a => ({ text: (a.innerText || "").trim().slice(0, 80), href: a.href }))
    .filter(l => l.text);
}

function payload() {
  const text = pickMainText();
  return {
    title: document.title || "",
    url: location.href,
    text: text.slice(0, 12000),
    snippets: collectSnippets(),
    forms: collectForms(),
    links: collectLinks(),
    readyState: document.readyState
  };
}

function syncContext() {
  chrome.runtime.sendMessage(
    { type: "page_context", payload: payload() },
    () => void chrome.runtime.lastError
  );
}

// ─── Browser Actions (agent can trigger these) ────────────────────────────────

function clickElement(selector) {
  const el = document.querySelector(selector);
  if (!el) return { ok: false, error: `Element not found: ${selector}` };
  el.click();
  return { ok: true, selector };
}

function fillInput(selector, value) {
  const el = document.querySelector(selector);
  if (!el) return { ok: false, error: `Element not found: ${selector}` };
  const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set
    || Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value")?.set;
  if (nativeInputValueSetter) nativeInputValueSetter.call(el, value);
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
  return { ok: true, selector, value };
}

function scrollPage(direction = "down", amount = 400) {
  window.scrollBy(0, direction === "down" ? amount : -amount);
  return { ok: true };
}

function getPageInfo() {
  return payload();
}

// ─── Debounced sync ───────────────────────────────────────────────────────────

let debounceTimer = null;
const debouncedSync = () => {
  if (debounceTimer) clearTimeout(debounceTimer);
  debounceTimer = setTimeout(syncContext, 500);
};

window.addEventListener("load", debouncedSync, { once: true });
window.addEventListener("hashchange", debouncedSync);
window.addEventListener("popstate", debouncedSync);

const observer = new MutationObserver(() => debouncedSync());
observer.observe(document.documentElement, { childList: true, subtree: true });

// ─── Message Listener ─────────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (!msg?.type) return false;

  if (msg.type === "collect_context") {
    sendResponse({ ok: true, payload: payload() });
    syncContext();
    return false;
  }

  if (msg.type === "browser_action") {
    const { action, selector, value, direction, amount } = msg;
    let result;
    switch (action) {
      case "click":        result = clickElement(selector); break;
      case "fill":         result = fillInput(selector, value); break;
      case "scroll":       result = scrollPage(direction, amount); break;
      case "get_page":     result = getPageInfo(); break;
      default:             result = { ok: false, error: `Unknown action: ${action}` };
    }
    sendResponse(result);
    return false;
  }

  return false;
});
