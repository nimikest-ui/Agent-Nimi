function pickMainText() {
  const candidates = [
    "main",
    "[role='main']",
    ".challenge-content",
    ".content",
    ".problem",
    ".task",
    "article"
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

function payload() {
  const text = pickMainText();
  return {
    title: document.title || "",
    url: location.href,
    text: text.slice(0, 12000),
    snippets: collectSnippets()
  };
}

function syncContext() {
  if (!location.href.startsWith("https://tdxarena.com/")) return;
  chrome.runtime.sendMessage(
    { type: "tdx_context", payload: payload() },
    () => void chrome.runtime.lastError
  );
}

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

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg?.type === "collect_context") {
    syncContext();
    sendResponse({ ok: true });
    return false;
  }
  return false;
});
