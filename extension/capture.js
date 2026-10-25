// Alt+Shift+L: save the whole current page as one self-contained .html file (SingleFile), asking where
// to save it. Loaded into the service worker by background.js (importScripts).
const SF_LIB = "vendor/singlefile/single-file.js";
const SF_HOOKS = "vendor/singlefile/single-file-hooks-frames.js";
const SF_OPTIONS = {
  removeHiddenElements: true,
  removeUnusedStyles: true,
  removeUnusedFonts: true,
  removeAlternativeFonts: true,
  removeAlternativeMedias: true,
  removeAlternativeImages: true,
  removeNoScriptTags: true,
  removeFrames: false,
  compressHTML: true,
  blockScripts: true,
  blockAudios: true,
  blockVideos: true,
  loadDeferredImages: true,          // scrolls through lazy-loaded images before saving
  loadDeferredImagesMaxIdleTime: 1500,
  groupDuplicateImages: true,
  maxSizeDuplicateImages: 512 * 1024,
  insertSingleFileComment: true,     // keeps the page URL and save date in the file
  resolveLinks: true,
};

// Blob URLs of our own saves: background.js must not treat them as Blackboard downloads to sort.
const captureUrls = new Set();

chrome.commands.onCommand.addListener((command, tab) => {
  if (command === "save-page" && tab) savePage(tab);
});

// SingleFile runs the timers of its lazy-content scroll here, where they are not throttled.
const lazyTimers = new Map();
chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (!sender.tab || !/^singlefile\.lazyTimeout\.(set|clear)Timeout$/.test(msg.method || "")) return false;
  const key = `${sender.tab.id}:${sender.frameId}:${msg.type}`;
  clearTimeout(lazyTimers.get(key));
  lazyTimers.delete(key);
  if (msg.method.endsWith("setTimeout")) {
    lazyTimers.set(key, setTimeout(() => {
      lazyTimers.delete(key);
      chrome.tabs.sendMessage(sender.tab.id, { method: "singlefile.lazyTimeout.onTimeout", type: msg.type },
                              { frameId: sender.frameId }).catch(() => {});
    }, msg.delay));
  }
  reply({});
  return false;
});

// Frames send their saved content to the top frame through here.
chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (!sender.tab || !/^singlefile\.frameTree\./.test(msg.method || "")) return false;
  chrome.tabs.sendMessage(sender.tab.id, msg, { frameId: 0 }).then(reply, () => reply({}));
  return true;
});

// Resources the page itself may not fetch (cross-origin images, fonts) are fetched here instead.
chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (msg.type !== "sf-fetch") return false;
  (async () => {
    try {
      const res = await fetch(msg.url, { credentials: "include" });
      const bytes = new Uint8Array(await res.arrayBuffer());
      reply({ status: res.status, url: res.url, headers: [...res.headers], data: bytes.toBase64() });
    } catch (e) {
      reply({ error: String(e && e.message || e) });
    }
  })();
  return true;
});

async function badge(tabId, text, title) {
  try {
    await chrome.action.setBadgeBackgroundColor({ tabId, color: text === "!" ? "#c62828" : "#2e7d32" });
    await chrome.action.setBadgeText({ tabId, text });
    await chrome.action.setTitle({ tabId, title: title || "Alt+O Blackboard Helper" });
  } catch (e) { /* tab closed */ }
}

function pageFileName(title) {
  const d = new Date();
  const date = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const name = (title || "page").replace(/[<>:"/\\|?*\x00-\x1f]/g, "_").replace(/\s+/g, " ").trim().slice(0, 150);
  return `${name || "page"} (${date}).html`;
}

async function savePage(tab) {
  const tabId = tab.id;
  await badge(tabId, "…", "Saving page…");
  let blobUrl = null;
  try {
    const all = { tabId, allFrames: true };
    await chrome.scripting.executeScript({ target: all, files: [SF_HOOKS], world: "MAIN" }).catch(() => {});
    await chrome.scripting.executeScript({ target: all, files: [SF_LIB] });
    await chrome.scripting.executeScript({ target: all, func: initSingleFile });
    const [{ result }] = await chrome.scripting.executeScript({ target: { tabId }, func: runSingleFile, args: [SF_OPTIONS] });
    if (!result || result.error) throw new Error(result ? result.error : "nothing captured");
    blobUrl = result.url;
    captureUrls.add(blobUrl);
    await badge(tabId, "…", "Choose where to save");
    const id = await chrome.downloads.download({ url: blobUrl, filename: pageFileName(result.title || tab.title),
                                                 saveAs: true, conflictAction: "uniquify" });
    const state = await downloadFinished(id);
    if (state === "complete") {
      await badge(tabId, "✓", `Saved (${Math.round(result.size / 1024)} KB)`);
      setTimeout(() => badge(tabId, ""), 4000);
    } else {
      await badge(tabId, "");                  // save dialog cancelled
    }
  } catch (e) {
    const msg = String(e && e.message || e);
    if (/cancel/i.test(msg)) { await badge(tabId, ""); }
    else { await badge(tabId, "!", "Could not save this page: " + msg); setTimeout(() => badge(tabId, ""), 8000); }
  } finally {
    if (blobUrl) {
      captureUrls.delete(blobUrl);
      chrome.scripting.executeScript({ target: { tabId }, func: (u) => URL.revokeObjectURL(u), args: [blobUrl] }).catch(() => {});
    }
  }
}

function downloadFinished(id) {
  return new Promise((resolve) => {
    const done = (state) => { chrome.downloads.onChanged.removeListener(onChange); resolve(state); };
    const onChange = (delta) => {
      if (delta.id === id && delta.state && delta.state.current !== "in_progress") done(delta.state.current);
    };
    chrome.downloads.onChanged.addListener(onChange);
    chrome.downloads.search({ id }).then(([it]) => { if (it && it.state !== "in_progress") done(it.state); });
  });
}

// ---- injected into the page (every frame) ---------------------------------------------
function initSingleFile() {
  if (singlefile.altoReady) return;              // a second save re-injects the library, so mark the instance
  singlefile.altoReady = true;
  const viaExtension = async (url) => {
    const r = await chrome.runtime.sendMessage({ type: "sf-fetch", url });
    if (!r || r.error) throw new Error(r ? r.error : "fetch failed");
    const bytes = Uint8Array.fromBase64(r.data);
    return { status: r.status, url: r.url, headers: new Headers(r.headers), arrayBuffer: async () => bytes.buffer };
  };
  const pageFetch = async (url, options) => {
    try { return await fetch(url, options); } catch (e) { return viaExtension(url); }
  };
  singlefile.init({ fetch: pageFetch, frameFetch: pageFetch });
}

async function runSingleFile(options) {
  try {
    const data = await singlefile.getPageData(options);
    const blob = new Blob([data.content], { type: "text/html" });
    return { url: URL.createObjectURL(blob), title: data.title || document.title, size: blob.size };
  } catch (e) {
    return { error: String(e && e.message || e) };
  }
}
