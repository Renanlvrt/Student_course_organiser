const APP = "http://127.0.0.1:47821";
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
let tab = null;
let info = null;
let found = [];

async function appStatus() {
  try {
    const r = await fetch(APP + "/status");
    const s = await r.json();
    $("dot").classList.toggle("on", s.active);
    $("app").textContent = s.active ? `Organiser ON · ${s.module || "Auto"}` : "Organiser OFF (Alt+O)";
    return s;
  } catch (e) {
    $("app").textContent = "Organiser not running";
    return null;
  }
}

function send(msg) {
  return chrome.tabs.sendMessage(tab.id, msg, { frameId: 0 });
}

async function init() {
  let status = await appStatus();
  if (!status) {                              // not running: start it, then carry on
    $("app").textContent = "Starting the organiser…";
    $("content").innerHTML = `<div class="muted">Starting the organiser…</div>`;
    await chrome.runtime.sendMessage({ type: "ensureApp" });
    status = await appStatus();
  }
  [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  try {
    info = await send({ type: "listSections" });
  } catch (e) {
    info = { error: "Open a Blackboard course page (reload it once after installing the extension)." };
  }
  if (!info || info.error) {
    $("content").innerHTML = `<div class="err">${esc(info ? info.error : "No response")}</div>`;
    return;
  }
  // Ticked sections: the ones picked last time for this course, else every section but the admin ones
  // (announcements, discussions, staff...) - courses lay out lectures, practicals and terms in many ways.
  const key = `ticks:${info.courseId}`;
  const saved = (await chrome.storage.local.get(key))[key];
  const ADMIN = /announce|discussion|forum|contact|staff|teaching team|calendar|grade|mark ?book|journal|blog|wiki|groups?$|email|messages|help|support|tools|panopto|recording|attendance|feedback survey|evaluation/i;
  const ticked = new Set(saved || info.sections.filter((s) => !ADMIN.test(s.title)).map((s) => s.id));
  const warn = !status ? `<div class="warn">The organiser app isn't running: files will just stay in Downloads.</div>`
    : `<div class="muted" style="margin-top:6px">Files downloaded from here are sorted automatically (no need for Alt+O).</div>`;
  $("content").innerHTML = `
    <div class="course">${esc(info.course.course_name)}</div>
    <div class="muted">${esc(info.course.course_code)}</div>
    ${warn}
    <div class="muted" style="margin-top:8px">Pick sections, then scan for files you don't have yet
      (<a href="#" id="all">all</a> · <a href="#" id="none">none</a>):</div>
    <ul id="secs">${info.sections.map((s) => `
      <li data-id="${esc(s.id)}"><input type="checkbox" ${ticked.has(s.id) ? "checked" : ""}><span>${esc(s.title)}</span><span class="n"></span></li>`).join("")}
    </ul>
    <button id="scan">Scan selected sections</button>
    <div id="result"></div>`;
  for (const li of document.querySelectorAll("#secs li")) {
    li.addEventListener("click", (ev) => {
      const cb = li.querySelector("input");
      if (ev.target !== cb) cb.checked = !cb.checked;
    });
  }
  const tickAll = (on) => (ev) => { ev.preventDefault(); for (const cb of document.querySelectorAll("#secs input")) cb.checked = on; };
  $("all").addEventListener("click", tickAll(true));
  $("none").addEventListener("click", tickAll(false));
  $("scan").addEventListener("click", scan);
  watchQueue();
}

async function scan() {
  const ids = [...document.querySelectorAll("#secs li")].filter((li) => li.querySelector("input").checked).map((li) => li.dataset.id);
  if (!ids.length) { $("result").innerHTML = `<div class="warn">Tick at least one section.</div>`; return; }
  chrome.storage.local.set({ [`ticks:${info.courseId}`]: ids });
  $("scan").disabled = true;
  $("result").innerHTML = `<div class="muted">Scanning (opening folders)…</div>`;
  const res = await send({ type: "collect", courseId: info.courseId, sectionIds: ids });
  $("scan").disabled = false;
  if (!res || res.error) { $("result").innerHTML = `<div class="err">${esc(res ? res.error : "No response")}</div>`; return; }
  const done = (await chrome.storage.local.get("downloaded")).downloaded || {};
  let have = new Set();
  try {
    const r = await fetch(APP + "/already", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ course_code: info.course.course_code, names: res.files.map((f) => f.fileName) }) });
    have = new Set(((await r.json()).have || []).map((n) => n.toLowerCase()));
  } catch (e) { /* app not running */ }
  found = res.files.filter((f) => !done[f.key] && !have.has((f.fileName || "").toLowerCase()));
  const skipped = res.files.length - found.length;
  const addBtn = (where, n, k) => k && (k.href || (k.add && k.add.href))
    ? `<button class="add" data-where="${where}" data-n="${n}" title="Add to the downloads">+</button>` : "";
  $("result").innerHTML = `
    <div class="muted" style="margin-top:8px">${res.files.length} file(s) found · <b style="color:var(--fg)">${found.length} new</b>${skipped ? ` · ${skipped} already downloaded` : ""}</div>
    <ul id="found"></ul>
    <button id="go"></button>
    ${(res.scanned || []).length ? `<details style="margin-top:8px"><summary class="muted" style="cursor:pointer">${res.scanned.length} item(s) checked</summary>
      <ul>${res.scanned.map((k, n) => `<li style="cursor:default"><span>${esc(k.title)}</span><span class="n">${k.page ? "page saved" : k.files ? `${k.files} file(s)` : esc(k.kind || "")}</span>${addBtn("scanned", n, k)}</li>`).join("")}</ul></details>` : ""}
    ${(res.skipped || []).length ? `<details style="margin-top:8px"><summary class="muted" style="cursor:pointer">${res.skipped.length} web link(s) skipped (Colab, blogs, web pages, not files)</summary>
      <ul>${res.skipped.slice(0, 40).map((k, n) => `<li style="cursor:default"><span>${esc(k.text)}</span><span class="n">${esc(k.line || k.section || "")}</span>${addBtn("skipped", n, k)}</li>`).join("")}</ul></details>` : ""}`;
  const renderFound = () => {
    $("found").innerHTML = found.slice(0, 80).map((f) => `<li style="cursor:default"><span>${esc(f.fileName || f.ctx.link_text || "file")}</span><span class="n">${esc(f.ctx.item_title || f.ctx.chain[0] || "")}</span></li>`).join("");
    $("go").disabled = !found.length;
    $("go").textContent = `Download ${found.length} new file(s)`;
  };
  renderFound();
  for (const b of document.querySelectorAll("button.add")) {
    b.addEventListener("click", () => {
      const k = res[b.dataset.where][+b.dataset.n];
      const f = linkDownload(k.add || k);
      if (!found.some((x) => x.key === f.key)) found.push(f);
      b.disabled = true;
      b.textContent = "✓";
      renderFound();
    });
  }
  $("go").addEventListener("click", async () => {
    $("go").disabled = true;
    // Sheets and slides first, notebooks/code last, so practical folders exist when code arrives.
    const isCode = (f) => /\.(ipynb|py|zip)(\?|$)/i.test(f.fileName || f.url);
    const ordered = found.filter((f) => !isCode(f)).concat(found.filter(isCode));
    await chrome.runtime.sendMessage({ type: "startQueue", files: ordered });
  });
}

// A web link added by hand: a GitHub/GitLab repository comes as a .zip of its code, any other page as a
// small .html file that opens it (the organiser files both next to the rest of the practical).
function linkDownload(k) {
  const url = new URL(k.href, tab.url).href;
  const ctx = { ...(k.ctx || {}), source: "manual-add" };
  const safe = (s) => (s || "link").replace(/[<>:"/\|?*\x00-\x1f]/g, "_").trim().slice(0, 120);
  let m = url.match(/^https:\/\/github\.com\/([^/]+)\/([^/#?]+?)(?:\.git)?(?:\/tree\/([^/#?]+))?\/?(?:[#?].*)?$/);
  if (m) return { key: `${info.courseId}:add:${url}`, url: `https://github.com/${m[1]}/${m[2]}/archive/${m[3] || "HEAD"}.zip`,
                  fileName: `${safe(m[2])}.zip`, ctx };
  m = url.match(/^https:\/\/gitlab\.com\/((?:[^/]+\/)+?([^/#?]+))\/?(?:[#?].*)?$/);
  if (m && !m[1].includes("/-/")) return { key: `${info.courseId}:add:${url}`, url: `https://gitlab.com/${m[1]}/-/archive/HEAD/${m[2]}-HEAD.zip`,
                                          fileName: `${safe(m[2])}.zip`, ctx };
  const title = esc(k.text || url);
  const doc = `<!doctype html><html><head><meta charset="utf-8"><title>${title}</title><meta http-equiv="refresh" content="0;url=${esc(url)}"></head>` +
    `<body><h1>${title}</h1><p><a href="${esc(url)}">${esc(url)}</a></p></body></html>`;
  return { key: `${info.courseId}:add:${url}`, url: "data:text/html;charset=utf-8," + encodeURIComponent(doc),
           fileName: `${safe(k.text)}.html`, ctx, page: true };
}

let lastQueue = null;

function renderQueue(q) {
  lastQueue = q;
  let box = $("queue");
  if (!q || !q.files || !q.files.length) { if (box) box.remove(); return; }
  if (!box) {
    box = document.createElement("div");
    box.id = "queue";
    $("content").appendChild(box);
  }
  const total = q.files.length;
  box.innerHTML = q.running
    ? `<progress max="${total}" value="${q.index}"></progress><div class="muted">Downloading ${Math.min(q.index + 1, total)}/${total}, one at a time…</div>
       <button class="secondary" id="cancel">Stop</button>`
    : `<div class="muted" style="margin-top:8px">Finished ${total} download(s)${q.failed ? `, <b style="color:var(--err)">${q.failed} FAILED</b> (open the recap to retry)` : ""}.</div>
       <button id="recap">See where they went</button>`;
  const rb = $("recap");
  if (rb) rb.onclick = async () => {
    // Save this batch ourselves so the recap never depends on the background having done it.
    const ctx = (q.files[0] && q.files[0].ctx) || {};
    await chrome.storage.local.set({ lastBatch: { at: Date.now(), course_code: ctx.course_code || "",
                                                  course_name: ctx.course_name || "", done: q.done || [] } });
    await chrome.tabs.create({ url: chrome.runtime.getURL("recap.html"), active: true });
  };
  const c = $("cancel");
  if (c) c.onclick = () => chrome.runtime.sendMessage({ type: "cancelQueue" });
}

async function watchQueue() {
  renderQueue((await chrome.storage.session.get("queue")).queue);
  chrome.storage.session.onChanged.addListener((ch) => { if (ch.queue) renderQueue(ch.queue.newValue); });
}

init();
