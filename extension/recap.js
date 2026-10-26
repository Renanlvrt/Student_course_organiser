// Recap of ONE download batch: a tree of where each file went, with drag-to-move.
const APP = "http://127.0.0.1:47821";
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const DOT = { sorted: ["●", "var(--ok)"], flagged: ["●", "var(--warn)"], duplicate: ["●", "var(--muted)"],
              skipped: ["●", "var(--muted)"], undone: ["●", "var(--muted)"] };

let batch = null;
let tax = null;
let entries = [];          // app entries belonging to this batch
let pollUntil = Date.now() + 120000;
let waiting = [];                                  // downloaded, but the organiser has no entry for it (yet)

async function api(path, body) {
  const r = await fetch(APP + path, body ? { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body) } : {});
  return r.json();
}

function toast(text) {
  const t = $("toast");
  t.textContent = text;
  t.classList.add("show");
  clearTimeout(toast.t);
  toast.t = setTimeout(() => t.classList.remove("show"), 2500);
}

async function load() {
  try {
    await loadInner();
  } catch (e) {
    $("summary").innerHTML = `<span class="msg">Couldn't build the recap: ${esc(e && e.message || e)}</span>`;
  }
}

async function loadInner() {
  batch = (await chrome.storage.local.get("lastBatch")).lastBatch;
  if (!batch || !batch.done || !batch.done.length) {
    $("summary").textContent = "No recent download batch from the extension.";
    return;
  }
  try { tax = await api("/taxonomy"); } catch (e) {
    $("summary").innerHTML = `<span class="msg">The organiser app isn't running, so files stayed in Downloads.</span>`;
    return;
  }
  await refresh();
}

async function refresh() {
  const recent = (await api("/recent")).entries;
  const byPath = {};
  for (const e of recent) {                       // newest first: keep the latest entry per original path
    const k = (e.original_path || "").toLowerCase();
    if (!byPath[k]) byPath[k] = e;
  }
  entries = [];
  let pending = 0;
  const byName = {};
  for (const e of recent) {
    const k = (e.original_name || "").toLowerCase();
    if (!byName[k]) byName[k] = e;
  }
  waiting = [];
  batch.done.forEach((d, i) => {
    if (!d.ok) return;
    const base = (d.path ? d.path.split(/[\\/]/).pop() : d.name || "").toLowerCase();
    const e = (d.path && byPath[d.path.toLowerCase()]) || byName[base];
    if (e) entries.push(e); else { pending++; waiting.push(i); }
  });
  render(pending);
  if (pending && Date.now() < pollUntil) setTimeout(refresh, Math.min(2000, pollUntil - Date.now() + 100));   // last pass shows what never sorted
}

// What a folder path means as a destination, e.g. ["Crypto","Symmetric Cryptography","Lectures","Lecture 03 - X"].
// Layout: Module/Lectures/<Part>/Lecture NN - X, Module/Practicals/<Part>/..., Module/Other.
function targetFor(parts) {
  const mod = tax.modules.find((m) => m.key === parts[0]);
  if (!mod || parts.length < 2) return null;
  if (parts[1] === "Other") return { module: mod.key, part: null, category: "Other" };
  if (parts[1] !== "Lectures" && parts[1] !== "Practicals") return null;
  if (parts[1] === "Lectures" && parts.slice(2, 4).includes("Readings")) {
    const rp = mod.parts.indexOf(parts[2]);
    return { module: mod.key, part: rp >= 0 ? rp : null, category: "Readings" };
  }
  const p = mod.parts.indexOf(parts[2]);
  if (p < 0) return null;
  const t = { module: mod.key, part: p, category: parts[1] };
  const m = parts.length >= 4 && parts[3].match(/^(Lecture|Practical) (\d+)/);
  if (m) t.number = parseInt(m[2], 10);
  return t;
}

function render(pending) {
  const sorted = entries.filter((e) => e.rel && e.rel[0] !== "_Unsorted").length;
  const unsure = entries.filter((e) => e.rel && e.rel[0] === "_Unsorted").length;
  const stayed = entries.filter((e) => !e.rel).length;
  const failed = batch.done.filter((d) => !d.ok).length;
  $("title").textContent = `Downloaded from ${batch.course_name || "Blackboard"}`;
  $("summary").innerHTML = [
    `${sorted} sorted`,
    unsure ? `<span style="color:var(--warn)">${unsure} to check</span>` : "",
    stayed ? `${stayed} left in Downloads` : "",
    failed ? `<span style="color:var(--err)">${failed} failed</span>` : "",
    pending ? `${pending} still sorting…` : "",
  ].filter(Boolean).join(" · ");

  // Build the folder tree from each file's path relative to courses\.
  const root = { kids: {}, files: [] };
  for (const e of entries.filter((x) => x.rel)) {
    let node = root;
    const folders = e.rel.slice(0, -1);
    folders.forEach((name, i) => {
      node.kids[name] = node.kids[name] || { kids: {}, files: [], path: folders.slice(0, i + 1) };
      node = node.kids[name];
    });
    node.files.push(e);
  }
  let html = `<ul class="tree">${renderKids(root)}</ul>`;
  const stayedList = entries.filter((e) => !e.rel);
  if (stayedList.length) html += `<div class="group">Left in Downloads</div><ul class="tree">${stayedList.map(fileRow).join("")}</ul>`;
  // Failures go first, in red, each with a Retry button.
  const failedIdx = batch.done.map((d, i) => (d.ok ? -1 : i)).filter((i) => i >= 0);
  if (failedIdx.length) {
    html = `<div class="failbox"><div class="failhead">✕ ${failedIdx.length} download${failedIdx.length > 1 ? "s" : ""} failed
        <button class="retry-all">Retry all</button></div>${failedIdx.map((i) => {
      const d = batch.done[i];
      return `<div class="failrow"><b>${esc(d.name)}</b><span>${esc(d.error || "download failed")}</span>
        ${d.url ? `<button class="retry" data-idx="${i}">Retry</button>` : `<span>scan again to retry</span>`}</div>`;
    }).join("")}</div>` + html;
  }
  // Downloaded but never sorted (after waiting): named in red, never left to go unnoticed.
  if (waiting.length && Date.now() >= pollUntil) {
    html = `<div class="failbox"><div class="failhead">✕ ${waiting.length} downloaded but not sorted (still in Downloads)
        <button class="sort-all">Sort now</button></div>${waiting.map((i) => `<div class="failrow"><b>${esc(batch.done[i].name)}</b>
        <span>${esc(batch.done[i].path || "")}</span></div>`).join("")}</div>` + html;
  }
  $("tree").innerHTML = html;
  const sortAll = document.querySelector("button.sort-all");
  if (sortAll) sortAll.onclick = async () => {
    sortAll.disabled = true;
    for (const i of waiting) {
      const d = batch.done[i];
      if (d.path) await api("/context", { ...(d.ctx || {}), path: d.path, url: d.url }).catch(() => null);
    }
    toast("Sorting…");
    pollUntil = Date.now() + 30000;
    await refresh();
  };
  for (const b of document.querySelectorAll("button.retry")) b.onclick = () => retry([parseInt(b.dataset.idx, 10)], b);
  const all = document.querySelector("button.retry-all");
  if (all) all.onclick = () => retry(failedIdx.filter((i) => batch.done[i].url), all);
  wire();
}

function renderKids(node) {
  let out = "";
  for (const name of Object.keys(node.kids).sort()) {
    const k = node.kids[name];
    const t = targetFor(k.path);
    const label = name === "_Unsorted" ? `<b style="color:var(--warn)">_Unsorted</b> (to check)` : `<b>${esc(name)}</b>`;
    out += `<li><span class="folder${t ? " drop" : ""}" ${t ? `data-target='${esc(JSON.stringify(t))}'` : ""}>📁 ${label}</span>
            <ul>${renderKids(k)}${k.files.slice().sort((a, b) => a.name.localeCompare(b.name)).map(fileRow).join("")}</ul></li>`;
  }
  return out;
}

function fileRow(e) {
  const [dot, colour] = DOT[e.status] || ["●", "var(--muted)"];
  const was = e.original_name !== e.name ? `<span class="was">was ${esc(e.original_name)}</span>` : "";
  const msg = e.status === "flagged" ? `<span class="msg">${esc(e.message || "check")}</span>`
    : !e.rel ? `<span class="was">${esc(e.message)}</span>` : "";
  const acts = e.status === "undone" ? "" : `<span class="acts"><a data-act="move">move</a>${e.rel ? `<a data-act="undo">undo</a>` : ""}</span>`;
  return `<li><div class="file" draggable="true" data-id="${esc(e.id)}">
    <span class="dot" style="color:${colour}">${dot}</span><span>${esc(e.rel ? e.name : e.original_name)}</span>${was}${msg}${acts}
  </div></li>`;
}

function wire() {
  for (const f of document.querySelectorAll(".file[data-id]")) {
    f.addEventListener("dragstart", (ev) => ev.dataTransfer.setData("text/plain", f.dataset.id));
    for (const a of f.querySelectorAll("a[data-act]")) {
      a.addEventListener("click", () => a.dataset.act === "move" ? openPicker(f) : undo(f.dataset.id));
    }
  }
  for (const d of document.querySelectorAll(".folder.drop")) {
    d.addEventListener("dragover", (ev) => { ev.preventDefault(); d.classList.add("over"); });
    d.addEventListener("dragleave", () => d.classList.remove("over"));
    d.addEventListener("drop", (ev) => {
      ev.preventDefault();
      d.classList.remove("over");
      move(ev.dataTransfer.getData("text/plain"), JSON.parse(d.dataset.target));
    });
  }
}

function openPicker(row) {
  document.querySelectorAll(".picker").forEach((p) => p.remove());
  document.querySelectorAll(".file.open").forEach((p) => p.classList.remove("open"));
  const e = entries.find((x) => x.id === row.dataset.id);
  row.classList.add("open");
  const box = document.createElement("div");
  box.className = "picker";
  box.innerHTML = `<select data-k="module">${tax.modules.map((m) => `<option value="${esc(m.key)}">${esc(m.key)}</option>`).join("")}</select>
    <select data-k="part"></select><select data-k="category"></select>
    <button>Move</button><button class="ghost">Cancel</button>`;
  row.after(box);
  const [sm, sp, sc] = box.querySelectorAll("select");
  sm.value = e.module || tax.modules[0].key;
  const fill = (keep) => {
    const mod = tax.modules.find((m) => m.key === sm.value);
    sp.innerHTML = mod.parts.map((p, i) => `<option value="${i}">${esc(p)}</option>`).join("") + `<option value="">Whole module</option>`;
    sp.value = keep && e.part !== null && e.part !== undefined ? String(e.part) : (keep && e.part === null ? "" : "0");
    fillCats(keep);
  };
  const fillCats = (keep) => {
    const cats = sp.value === "" ? tax.module_categories : tax.part_categories;
    const prev = keep ? e.category : sc.value;
    sc.innerHTML = cats.map((c) => `<option>${esc(c)}</option>`).join("");
    if (cats.includes(prev)) sc.value = prev;
  };
  sm.onchange = () => fill(false);
  sp.onchange = () => fillCats(false);
  fill(true);
  const [go, cancel] = box.querySelectorAll("button");
  cancel.onclick = () => { box.remove(); row.classList.remove("open"); };
  go.onclick = () => move(e.id, { module: sm.value, part: sp.value === "" ? null : parseInt(sp.value, 10), category: sc.value });
}

async function move(id, target) {
  const body = { id, module: target.module, part: target.part, category: target.category };
  if (target.number) body.number = target.number;
  const r = await api("/move", body);
  if (r.ok) toast(`Moved to ${r.entry.where}`);
  else toast(r.error === "need_part" ? "Pick a part for that type" : `Couldn't move: ${r.error}`);
  await refresh();
}

// Retry failed downloads: first in the browser (has your Blackboard login), then via the organiser.
async function retry(indexes, button) {
  button.disabled = true;
  button.textContent = "Retrying…";
  for (const i of indexes) {
    const d = batch.done[i];
    let ok = false, err = d.error;
    try {
      const id = await chrome.downloads.download({ url: d.url, conflictAction: "uniquify", saveAs: false });
      ok = await new Promise((res) => {
        const h = (delta) => {
          if (delta.id !== id || !delta.state) return;
          if (delta.state.current === "complete" || delta.state.current === "interrupted") {
            chrome.downloads.onChanged.removeListener(h);
            res(delta.state.current === "complete");
          }
        };
        chrome.downloads.onChanged.addListener(h);
      });
      if (ok) {
        const [it] = await chrome.downloads.search({ id });
        d.path = it.filename;
        await api("/context", { ...(d.ctx || {}), path: it.filename, url: d.url });
      }
    } catch (e) { err = String(e && e.message || e); }
    if (!ok) {
      const r = await api("/fetch", { url: d.url, name: null, ctx: d.ctx || {} });
      ok = r.ok;
      if (ok) d.path = r.entry.original_path; else err = r.error;
    }
    Object.assign(d, ok ? { ok: true, error: undefined } : { error: `still failing: ${err}` });
  }
  await chrome.storage.local.set({ lastBatch: batch });
  toast("Retry finished");
  pollUntil = Date.now() + 60000;
  await refresh();
}

async function undo(id) {
  await api("/undo", { id });
  toast("Moved back to Downloads");
  await refresh();
}

load();
