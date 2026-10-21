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
  const status = await appStatus();
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
  const warn = !status ? `<div class="warn">The organiser app isn't running: files will just stay in Downloads.</div>`
    : `<div class="muted" style="margin-top:6px">Files downloaded from here are sorted automatically (no need for Alt+O).</div>`;
  $("content").innerHTML = `
    <div class="course">${esc(info.course.course_name)}</div>
    <div class="muted">${esc(info.course.course_code)}</div>
    ${warn}
    <div class="muted" style="margin-top:8px">Pick sections, then scan for files you don't have yet:</div>
    <ul id="secs">${info.sections.map((s) => `
      <li data-id="${esc(s.id)}"><input type="checkbox"><span>${esc(s.title)}</span><span class="n"></span></li>`).join("")}
    </ul>
    <button id="scan">Scan selected sections</button>
    <div id="result"></div>`;
  for (const li of document.querySelectorAll("#secs li")) {
    li.addEventListener("click", (ev) => {
      const cb = li.querySelector("input");
      if (ev.target !== cb) cb.checked = !cb.checked;
    });
  }
  $("scan").addEventListener("click", scan);
  watchQueue();
}

async function scan() {
  const ids = [...document.querySelectorAll("#secs li")].filter((li) => li.querySelector("input").checked).map((li) => li.dataset.id);
  if (!ids.length) { $("result").innerHTML = `<div class="warn">Tick at least one section.</div>`; return; }
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
  $("result").innerHTML = `
    <div class="muted" style="margin-top:8px">${res.files.length} file(s) found · <b style="color:var(--fg)">${found.length} new</b>${skipped ? ` · ${skipped} already downloaded` : ""}</div>
    <ul>${found.slice(0, 60).map((f) => `<li style="cursor:default"><span>${esc(f.fileName || f.ctx.link_text || "file")}</span><span class="n">${esc(f.ctx.item_title || f.ctx.chain[0] || "")}</span></li>`).join("")}</ul>
    <button id="go" ${found.length ? "" : "disabled"}>Download ${found.length} new file(s)</button>
    ${(res.skipped || []).length ? `<details style="margin-top:8px"><summary class="muted" style="cursor:pointer">${res.skipped.length} web link(s) skipped (Colab, blogs, web pages, not files)</summary>
      <ul>${res.skipped.slice(0, 40).map((k) => `<li style="cursor:default"><span>${esc(k.text)}</span><span class="n">${esc(k.line || k.section || "")}</span></li>`).join("")}</ul></details>` : ""}`;
  $("go") && $("go").addEventListener("click", async () => {
    $("go").disabled = true;
    await chrome.runtime.sendMessage({ type: "startQueue", files: found });
  });
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
    : `<div class="muted" style="margin-top:8px">Finished ${total} download(s)${q.failed ? `, ${q.failed} failed` : ""}.</div>
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
