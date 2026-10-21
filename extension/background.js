// Service worker: tags Blackboard downloads with course/section context and runs the
// gentle one-at-a-time "download all new" queue. State lives in chrome.storage so it
// survives the worker being suspended.
const APP = "http://127.0.0.1:47821";
const BB_HOST = /(^|\.)durham\.ac\.uk$|(^|\.)blackboard\.com$/;
const GAP_MS = 1200;

const session = chrome.storage.session;
const local = chrome.storage.local;

const isBB = (url) => { try { return BB_HOST.test(new URL(url).hostname); } catch (e) { return false; } };

// ---- keep the organiser app running ---------------------------------------------------
// If it is not running (after a reboot before login items ran, a crash, or Quit), start it through the
// native-messaging launcher registered by scripts/install_native_host.ps1.
async function appUp() {
  try { return (await fetch(APP + "/status")).ok; } catch (e) { return false; }
}

let starting = null;
function ensureApp() {
  if (!starting) {
    starting = (async () => {
      if (await appUp()) return true;
      try { await chrome.runtime.sendNativeMessage("com.alto.organiser", { cmd: "start" }); } catch (e) { /* not installed */ }
      for (let i = 0; i < 40; i++) {
        if (await appUp()) return true;
        await new Promise((r) => setTimeout(r, 500));
      }
      return false;
    })().finally(() => { setTimeout(() => { starting = null; }, 1000); });
  }
  return starting;
}

chrome.runtime.onStartup.addListener(() => { ensureApp(); });
chrome.runtime.onInstalled.addListener(() => { ensureApp(); });

async function getS(key, dflt) { const r = await session.get(key); return r[key] ?? dflt; }
async function setS(key, val) { await session.set({ [key]: val }); }

// ---- clicks reported by content scripts (any frame) --------------------------------
chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (msg.type === "click" && sender.tab) {
    (async () => {
      const clicks = await getS("clicks", {});
      const tab = String(sender.tab.id);
      const prev = clicks[tab] ? clicks[tab].last : null;
      clicks[tab] = { last: { ...msg.click, t: Date.now() }, prev };
      await setS("clicks", clicks);
    })();
    return false;
  }
  if (msg.type === "ensureApp") {
    ensureApp().then((ok) => reply({ ok }));
    return true;
  }
  if (msg.type === "startQueue") {
    startQueue(msg.files).then(() => reply({ ok: true }));
    return true;
  }
  if (msg.type === "cancelQueue") {
    session.set({ queue: { files: [], index: 0, running: false, cancelled: true } }).then(() => reply({ ok: true }));
    return true;
  }
  return false;
});

// ---- tagging every download that comes from Blackboard ------------------------------
// The context lookup (REST calls) can take longer than a small download, so onCreated
// registers a promise synchronously and onChanged(complete) awaits it.
const ctxReady = new Map();

chrome.downloads.onCreated.addListener((item) => {
  if (isBB(item.url) || isBB(item.referrer || "") || isBB(item.finalUrl || "")) {
    fetch(APP + "/status").catch(() => {});      // tells the app a tagged download is on its way
  }
  ctxReady.set(item.id, resolveCtx(item).catch(() => null));
});

async function resolveCtx(item) {
  const ctxs = await getS("ctx", {});
  const pending = await getS("pendingByUrl", {});
  if (pending[item.url]) {                       // started by our queue
    const ctx = pending[item.url];
    ctxs[item.id] = ctx;
    delete pending[item.url];
    await setS("pendingByUrl", pending);
    await setS("ctx", ctxs);
    return ctx;
  }
  const fromBB = isBB(item.url) || isBB(item.referrer || "") || isBB(item.finalUrl || "");
  const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  const tabBB = tab && isBB(tab.url || "");
  if (!fromBB && !tabBB) return null;
  if (!fromBB) fetch(APP + "/status").catch(() => {});
  let ctx = {};
  if (tabBB) {
    try {
      ctx = await chrome.tabs.sendMessage(tab.id, { type: "context", url: item.finalUrl || item.url }, { frameId: 0 }) || {};
    } catch (e) { ctx = {}; }
    const clicks = (await getS("clicks", {}))[String(tab.id)] || {};
    const fresh = (c) => c && Date.now() - c.t < 180000;
    if (ctx.rest_chain && ctx.rest_chain.length) {
      ctx.item_title = ctx.rest_chain[0];
      ctx.chain = ctx.rest_chain.slice(1);
      ctx.source = "rest";
    } else {
      ctx.chain = fresh(clicks.last) ? clicks.last.chain : [];
      ctx.prev_chain = fresh(clicks.prev) ? clicks.prev.chain : [];
      ctx.item_title = fresh(clicks.last) ? clicks.last.item_title : "";
      ctx.source = "dom";
      if (!ctx.course_code && fresh(clicks.last)) ctx.course_code = clicks.last.course_code || "";
    }
    delete ctx.rest_chain;
  }
  const all = await getS("ctx", {});
  all[item.id] = ctx;
  await setS("ctx", all);
  return ctx;
}

chrome.downloads.onChanged.addListener(async (delta) => {
  if (!delta.state) return;
  const state = delta.state.current;
  if (state !== "complete" && state !== "interrupted") return;
  let ctx;
  const ready = ctxReady.get(delta.id);
  if (ready) {
    ctx = await Promise.race([ready, new Promise((r) => setTimeout(() => r(undefined), 8000))]);
    ctxReady.delete(delta.id);
  }
  const ctxs = await getS("ctx", {});
  if (ctx === undefined) ctx = ctxs[delta.id] || null;   // worker was restarted, or lookup timed out
  let finalPath = null;
  if (state === "complete") {
    const [it] = await chrome.downloads.search({ id: delta.id });
    if (it) finalPath = it.filename;               // recorded even if the context lookup failed
  }
  if (ctx && state === "complete") {
    const [item] = await chrome.downloads.search({ id: delta.id });
    if (item) {
      await ensureApp();                      // the organiser sorts files already sitting in Downloads
      try {
        await fetch(APP + "/context", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ...ctx, path: item.filename, url: item.finalUrl || item.url }),
        });
      } catch (e) { /* organiser not running: file simply stays in Downloads */ }
    }
    if (ctx.key) {
      const done = (await local.get("downloaded")).downloaded || {};
      done[ctx.key] = Date.now();
      await local.set({ downloaded: done });
    }
  }
  if (ctxs[delta.id]) { delete ctxs[delta.id]; await setS("ctx", ctxs); }
  const q = await getS("queue", null);
  const isCurrent = q && q.running && (q.currentId === delta.id ||
    (!q.currentId && ctx && q.files[q.index] && ctx.key === q.files[q.index].key));
  if (isCurrent) {
    q.currentId = null;
    await setS("queue", q);
    if (state === "complete") {
      await settle(q, { ok: true, path: finalPath });
    } else {
      const [it] = await chrome.downloads.search({ id: delta.id });
      await failed(q, (it && it.error) || "INTERRUPTED");
    }
  }
});

// A finished queue item: record it and move on.
async function settle(q, result) {
  const f = q.files[q.index];
  q.done = (q.done || []).concat([{ name: f.fileName || (f.ctx && f.ctx.link_text) || "file", ...result,
                                    ...(result.ok ? {} : { url: f.url, key: f.key, ctx: f.ctx }) }]);
  if (!result.ok) q.failed = (q.failed || 0) + 1;
  q.index += 1;
  q.currentId = null;
  await setS("queue", q);
  setTimeout(nextInQueue, GAP_MS);
}

// Browser download failed: retry twice, then ask the organiser to fetch it, then report it clearly.
async function failed(q, reason) {
  const f = q.files[q.index];
  f.attempts = (f.attempts || 0) + 1;
  if (f.attempts <= 2) {
    await setS("queue", q);
    setTimeout(nextInQueue, 2500 * f.attempts);
    return;
  }
  await ensureApp();
  try {
    const r = await (await fetch(APP + "/fetch", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: f.url, name: /\.[a-z0-9]{1,5}$/i.test(f.fileName || "") ? f.fileName : null,
                             ctx: { ...f.ctx, key: f.key } }),
    })).json();
    if (r.ok) {
      const done = (await local.get("downloaded")).downloaded || {};
      done[f.key] = Date.now();
      await local.set({ downloaded: done });
      return settle(q, { ok: true, path: r.entry.original_path, via: "organiser" });
    }
    return settle(q, { ok: false, error: `${reason}; organiser retry: ${r.error}` });
  } catch (e) {
    return settle(q, { ok: false, error: `${reason} (organiser not running)` });
  }
}

// ---- "download all new files" queue -------------------------------------------------
// Save this batch and show where every file went.
async function openRecap(q) {
  if (!q.done || !q.done.length || q.cancelled) return;
  const ctx = (q.files[0] && q.files[0].ctx) || {};
  await local.set({ lastBatch: { at: Date.now(), course_code: ctx.course_code || "", course_name: ctx.course_name || "",
                                 done: q.done } });
  // Give the organiser a moment to sort the last file before the page opens.
  setTimeout(() => chrome.tabs.create({ url: chrome.runtime.getURL("recap.html") }), 2500);
}

async function startQueue(files) {
  await ensureApp();
  await setS("queue", { files, index: 0, running: true, currentId: null, failed: 0, done: [] });
  nextInQueue();
}

function safeName(name) {
  return (name || "file").replace(/[<>:"/\\|?*\x00-\x1f]/g, "_").replace(/^\.+/, "").slice(0, 180) || "file";
}

async function nextInQueue() {
  const q = await getS("queue", null);
  if (!q || !q.running || q.currentId) return;
  if (q.index >= q.files.length) {
    q.running = false;
    await setS("queue", q);
    await openRecap(q);
    return;
  }
  const f = q.files[q.index];
  const pending = await getS("pendingByUrl", {});
  pending[f.url] = { ...f.ctx, key: f.key };
  await setS("pendingByUrl", pending);
  try {
    // Only force a filename when it has an extension; otherwise the server's name (with .pdf etc.) wins.
    const opts = { url: f.url, conflictAction: "uniquify", saveAs: false };
    if (/\.[a-z0-9]{1,5}$/i.test(f.fileName || "")) opts.filename = safeName(f.fileName);
    const id = await chrome.downloads.download(opts);
    const now = await getS("queue", null);      // it may already have finished (tiny file)
    if (now && now.running && now.index === q.index) {
      now.currentId = id;
      await setS("queue", now);
    }
  } catch (e) {
    await failed(q, String(e && e.message || e));
  }
}
