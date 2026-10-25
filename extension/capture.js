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
  if (command === "clip-region" && tab) startClip(tab);
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

// ---- Alt+L: clip a region (clip.js) -------------------------------------------------------
const READER = chrome.runtime.getURL("vendor/pdfjs/web/viewer.html");
const readerUrl = (src, clip) => `${READER}?src=${encodeURIComponent(src)}${clip ? "&clip=1" : ""}`;

async function startClip(tab) {
  const tabId = tab.id;
  if ((tab.url || "").startsWith(READER)) {        // our reader: it starts the overlay itself
    chrome.runtime.sendMessage({ type: "clip-start", tabId }).catch(() => {});
    return;
  }
  try {
    await chrome.scripting.executeScript({ target: { tabId }, files: ["clip.js"] });
    await chrome.scripting.executeScript({ target: { tabId }, func: () => globalThis.altoClip.start() });
  } catch (e) {
    if (await isPdf(tab.url || "")) {
      await chrome.tabs.update(tabId, { url: readerUrl(tab.url, true) });   // reopen in the reader, then clip
      return;
    }
    await badge(tabId, "!", "Alt+L can't run on this page: " + String(e && e.message || e));
    setTimeout(() => badge(tabId, ""), 6000);
  }
}

// A tab that can't be scripted may be Chrome's own PDF viewer (reader turned off, or opened before).
async function isPdf(url) {
  if (/^file:.*\.pdf$/i.test(url)) return true;
  if (!/^https?:/.test(url)) return false;
  try {
    const res = await fetch(url, { method: "HEAD", credentials: "include" });
    return /application\/pdf/i.test(res.headers.get("content-type") || "") || /\.pdf([?#]|$)/i.test(url);
  } catch (e) { return /\.pdf([?#]|$)/i.test(url); }
}

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (msg.type === "clip-shot" && sender.tab) {
    chrome.tabs.captureVisibleTab(sender.tab.windowId, { format: "png" })
      .then((dataUrl) => reply({ dataUrl }), (e) => reply({ error: String(e && e.message || e) }));
    return true;
  }
  if (msg.type === "clip-save") {
    (async () => {
      captureUrls.add(msg.url);
      try {
        const id = await chrome.downloads.download({ url: msg.url, filename: msg.filename, saveAs: true, conflictAction: "uniquify" });
        reply({ state: await downloadFinished(id) });
      } catch (e) {
        reply({ error: String(e && e.message || e) });
      } finally {
        captureUrls.delete(msg.url);
      }
    })();
    return true;
  }
  return false;
});

// ---- PDFs open in the built-in reader (so Alt+L can clip them exactly) -----------------------
// declarativeNetRequest redirects before Chrome's own viewer loads, as Mozilla's PDF.js extension does
// (mozilla/pdf.js extensions/chromium/pdfHandler.js). Unlike it, attachments are left alone: those are
// Blackboard downloads the organiser sorts. On by default; toggled from the icon's right-click menu.
const READER_KEY = "pdfReader";
const readerOn = async () => (await chrome.storage.local.get(READER_KEY))[READER_KEY] !== false;
const RULE_IDS = [1, 2, 3];

async function applyReaderRules() {
  const redirect = { type: "redirect", redirect: { regexSubstitution: READER + "?DNR:\\0" } };
  const addRules = (await readerOn()) ? [
    { id: 1, priority: 3, action: { type: "allow" },
      condition: { urlFilter: "*", resourceTypes: ["main_frame"],
                   responseHeaders: [{ header: "content-disposition", values: ["attachment*"] }] } },
    { id: 2, priority: 2, action: redirect,
      condition: { regexFilter: "^.*$", resourceTypes: ["main_frame"], excludedRequestMethods: ["post"],
                   responseHeaders: [{ header: "content-type", values: ["application/pdf", "application/pdf;*"] }] } },
    { id: 3, priority: 1, action: redirect,       // local files (needs "Allow access to file URLs")
      condition: { regexFilter: "^file://.*\\.pdf$", resourceTypes: ["main_frame"] } },
  ] : [];
  await chrome.declarativeNetRequest.updateDynamicRules({ removeRuleIds: RULE_IDS, addRules });
}

chrome.runtime.onInstalled.addListener(async () => {
  chrome.contextMenus.create({ id: READER_KEY, title: "Open PDFs in the built-in reader (for Alt+L)",
                               type: "checkbox", checked: await readerOn(), contexts: ["action"] });
  applyReaderRules();
});
chrome.runtime.onStartup.addListener(applyReaderRules);
chrome.contextMenus.onClicked.addListener(async (info) => {
  if (info.menuItemId !== READER_KEY) return;
  await chrome.storage.local.set({ [READER_KEY]: info.checked });
  applyReaderRules();
});
