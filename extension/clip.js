// Alt+L: drag a box (or click a block) and the content under it goes to the clipboard, ready for Ctrl+V.
//   Image mode (default): one exact picture of the box, at the screen's own pixel size (pastes like Win+Shift+S).
//   Text mode:  real text with its formatting; images, diagrams, formulas and other visuals come along as exact
//               crops of the screen. Also puts plain text and a PNG of the whole box on the clipboard.
// In the built-in PDF reader the picture is re-rendered from the PDF at screen resolution, the text comes from the PDF,
// and "Save…" writes a cropped vector PDF of just the box.
// Injected into web pages by capture.js; included by the PDF reader (vendor/pdfjs/web/viewer.html).
(() => {
  if (globalThis.altoClip) return;

  const isPdf = () => !!(globalThis.PDFViewerApplication && globalThis.PDFViewerApplication.pdfDocument);
  const MODE_KEY = "clipMode";                     // { web: "text" | "image", pdf: "text" | "image" }
  const DEFAULT_MODES = { web: "image", pdf: "image" };

  let active = null;                               // the open overlay, if any

  // ---- overlay -------------------------------------------------------------------------------
  const CSS = `
    :host { all: initial; }
    .layer { position: fixed; inset: 0; z-index: 2147483647; cursor: crosshair; background: rgba(15,23,42,.28); }
    .layer.has-box { background: transparent; }
    .box { position: fixed; border: 2px solid #fff; outline: 1px solid rgba(37,99,235,.9);
           box-shadow: 0 0 0 100vmax rgba(15,23,42,.38); pointer-events: none; display: none; }
    .hover { position: fixed; border: 2px dashed #60a5fa; background: rgba(96,165,250,.12); pointer-events: none; display: none; }
    .size { position: fixed; font: 600 11px/1 system-ui, sans-serif; color: #fff; background: rgba(15,23,42,.85);
            padding: 4px 6px; border-radius: 4px; pointer-events: none; display: none; }
    .bar { position: fixed; top: 14px; left: 50%; transform: translateX(-50%); display: flex; gap: 6px; align-items: center;
           font: 13px/1 system-ui, sans-serif; color: #e2e8f0; background: rgba(15,23,42,.92); padding: 6px; border-radius: 10px;
           box-shadow: 0 6px 24px rgba(0,0,0,.35); cursor: default; user-select: none; }
    .bar button { all: unset; padding: 7px 11px; border-radius: 7px; cursor: pointer; color: #cbd5e1; }
    .bar button:hover { background: rgba(148,163,184,.18); }
    .bar button.on { background: #2563eb; color: #fff; }
    .bar u { text-decoration: none; opacity: .65; font-size: 11px; margin-left: 4px; }
    .hint { padding: 0 8px 0 4px; opacity: .7; font-size: 12px; }
    .toast { position: fixed; right: 18px; bottom: 18px; z-index: 2147483647; display: flex; gap: 10px; align-items: center;
             font: 13px/1.3 system-ui, sans-serif; color: #f1f5f9; background: rgba(15,23,42,.95); padding: 10px 12px;
             border-radius: 10px; box-shadow: 0 6px 24px rgba(0,0,0,.35); }
    .toast.err { background: #991b1b; }
    .toast button { all: unset; cursor: pointer; padding: 5px 9px; border-radius: 6px; background: rgba(148,163,184,.22); }
    .toast button:hover { background: rgba(148,163,184,.4); }
  `;

  function makeHost() {
    const host = document.createElement("alto-clip");
    host.style.cssText = "position:fixed;top:0;left:0;z-index:2147483647";   // above the page's own stacking contexts
    const root = host.attachShadow({ mode: "closed" });
    const sheet = new CSSStyleSheet();             // constructable sheets are not blocked by page CSPs
    sheet.replaceSync(CSS);
    root.adoptedStyleSheets = [sheet];
    (document.body || document.documentElement).appendChild(host);
    return { host, root };
  }

  async function loadModes() {
    try { return { ...DEFAULT_MODES, ...((await chrome.storage.local.get(MODE_KEY))[MODE_KEY] || {}) }; }
    catch (e) { return { ...DEFAULT_MODES }; }
  }

  async function start() {
    if (active) return;
    const modes = await loadModes();
    const kind = isPdf() ? "pdf" : "web";
    let mode = modes[kind];
    const { host, root } = makeHost();
    const layer = el("div", "layer"), box = el("div", "box"), hover = el("div", "hover"), size = el("div", "size");
    const bar = el("div", "bar");
    const textBtn = el("button"), imgBtn = el("button");
    imgBtn.innerHTML = "Exact image<u>I</u>";
    textBtn.innerHTML = "Editable text<u>T</u>";
    const hint = el("span", "hint");
    hint.textContent = kind === "pdf" ? "Drag a box · click = whole page · Esc" : "Drag a box · click a block · Esc";
    bar.append(imgBtn, textBtn, hint);
    root.append(layer, hover, box, size, bar);
    const paint = () => { textBtn.classList.toggle("on", mode === "text"); imgBtn.classList.toggle("on", mode === "image"); };
    const setMode = (m) => {
      mode = m; paint();
      modes[kind] = m;
      try { chrome.storage.local.set({ [MODE_KEY]: modes }); } catch (e) { /* storage unavailable */ }
    };
    paint();

    let startPt = null, dragging = false, picked = null;
    const close = () => {
      host.remove();
      window.removeEventListener("keydown", onKey, true);
      active = null;
    };
    active = { close };

    const pick = (x, y) => {                       // block under the cursor, for click-to-clip
      host.style.pointerEvents = "none";
      layer.style.pointerEvents = "none";
      const target = document.elementFromPoint(x, y);
      host.style.pointerEvents = "";
      layer.style.pointerEvents = "";
      return kind === "pdf" ? pdfPageRect(target) : blockRect(target);
    };
    const show = (node, r) => {
      if (!r) { node.style.display = "none"; return; }
      Object.assign(node.style, { display: "block", left: r.left + "px", top: r.top + "px",
                                  width: r.width + "px", height: r.height + "px" });
    };

    // Pointer events: the PDF reader cancels pointerdown, which would suppress the mouse* events.
    layer.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) { close(); return; }
      e.preventDefault();
      layer.setPointerCapture(e.pointerId);
      startPt = { x: e.clientX, y: e.clientY };
      dragging = false;
    });
    layer.addEventListener("pointermove", (e) => {
      if (!startPt) {
        picked = pick(e.clientX, e.clientY);
        show(hover, picked);
        return;
      }
      if (!dragging && Math.hypot(e.clientX - startPt.x, e.clientY - startPt.y) < 5) return;
      dragging = true;
      hover.style.display = "none";
      layer.classList.add("has-box");
      const r = rectFrom(startPt, { x: e.clientX, y: e.clientY });
      show(box, r);
      Object.assign(size.style, { display: "block", left: r.left + "px", top: Math.max(0, r.top - 22) + "px" });
      size.textContent = `${Math.round(r.width)} × ${Math.round(r.height)}`;
    });
    layer.addEventListener("pointerup", (e) => {
      if (!startPt) return;
      const r = dragging ? rectFrom(startPt, { x: e.clientX, y: e.clientY }) : picked;
      startPt = null;
      if (!r || r.width < 4 || r.height < 4) return;
      close();
      finish(r, mode, kind);
    });
    layer.addEventListener("wheel", (e) => {
      const scroller = kind === "pdf" ? document.getElementById("viewerContainer") : null;
      (scroller || window).scrollBy(e.deltaX, e.deltaY);
      e.preventDefault();
    }, { passive: false });
    layer.addEventListener("contextmenu", (e) => { e.preventDefault(); close(); });
    textBtn.addEventListener("click", () => setMode("text"));
    imgBtn.addEventListener("click", () => setMode("image"));
    bar.addEventListener("pointerdown", (e) => e.stopPropagation());

    function onKey(e) {
      const k = e.key.toLowerCase();
      if (k === "escape") close();
      else if (k === "t") setMode("text");
      else if (k === "i") setMode("image");
      else return;
      e.preventDefault();
      e.stopPropagation();
    }
    window.addEventListener("keydown", onKey, true);
  }

  // ---- after the box is chosen ---------------------------------------------------------------
  // The clipboard write starts right away (inside the mouse-up gesture) with promises for each format.
  function finish(rect, mode, kind) {
    const work = kind === "pdf" ? pdfClip(rect, mode) : webClip(rect, mode);
    const item = {};
    item["image/png"] = work.then((r) => r.png);  // Chrome also writes it as a Windows bitmap
    if (mode === "text") {                         // image mode stays a plain picture, which every app pastes
      item["text/html"] = work.then((r) => new Blob([r.html], { type: "text/html" }));
      item["text/plain"] = work.then((r) => new Blob([r.text], { type: "text/plain" }));
    }
    navigator.clipboard.write([new ClipboardItem(item)]).then(
      async () => toast((await work).summary, (await work).save),
      async (e) => {
        let detail = String(e && e.message || e);
        try { await work; } catch (w) { detail = String(w && w.message || w); }
        console.warn("Alt+L:", detail);
        toast("Couldn't copy: " + detail, null, true);
      });
  }

  function toast(message, save, error) {
    const { host, root } = makeHost();
    const t = el("div", "toast" + (error ? " err" : ""));
    const span = el("span");
    span.textContent = message;
    t.append(span);
    if (save) {
      const b = el("button");
      b.textContent = "Save…";
      b.addEventListener("click", () => { save().catch((e) => alert("Save failed: " + e)); host.remove(); });
      t.append(b);
    }
    root.append(t);
    setTimeout(() => host.remove(), save ? 6000 : 4000);
  }

  // ---- web pages -----------------------------------------------------------------------------
  async function webClip(sel, mode) {
    const shot = screenshot();                     // overlay is already gone; capture waits a frame
    const plan = mode === "text" ? extract(sel) : null;
    const img = await shot;
    const ratio = img.width / window.innerWidth;
    const png = await cropPng(img, sel, ratio);
    const pngUri = await blobToDataUri(png);
    const w = Math.round(sel.width), h = Math.round(sel.height);
    let html, text = "", summary;
    if (plan) {
      await Promise.all(plan.visuals.map(async ({ node, rect }) => {
        node.src = await blobToDataUri(await cropPng(img, rect, ratio));
      }));
      html = plan.root.outerHTML;
      text = plan.text;
      summary = text.trim() ? `Copied text${plan.visuals.length ? " + " + plural(plan.visuals.length, "picture") : ""} · Ctrl+V`
                            : "Copied picture · Ctrl+V";
      if (!text.trim() && !plan.visuals.length) html = imgTag(pngUri, w, h);
    } else {
      html = imgTag(pngUri, w, h);
      summary = "Copied exact image · Ctrl+V";
    }
    const save = () => saveBlob(png, fileStem(document.title) + " clip.png");
    return { png, html, text, summary, save };
  }

  async function screenshot() {
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    const r = await chrome.runtime.sendMessage({ type: "clip-shot" });
    if (!r || r.error) throw new Error(r ? r.error : "no screenshot");
    const bytes = Uint8Array.fromBase64(r.dataUrl.slice(r.dataUrl.indexOf(",") + 1));
    return createImageBitmap(new Blob([bytes], { type: "image/png" }));
  }

  async function cropPng(img, r, ratio) {
    const sx = Math.max(0, Math.round(r.left * ratio)), sy = Math.max(0, Math.round(r.top * ratio));
    const sw = Math.max(1, Math.min(img.width - sx, Math.round(r.width * ratio)));
    const sh = Math.max(1, Math.min(img.height - sy, Math.round(r.height * ratio)));
    const c = new OffscreenCanvas(sw, sh);
    c.getContext("2d").drawImage(img, sx, sy, sw, sh, 0, 0, sw, sh);
    return c.convertToBlob({ type: "image/png" });
  }

  // Rebuilds the part of the page inside `sel` as clean HTML with inline styles. Text is cut at word level
  // on the box edges; visual elements become <img> placeholders filled with screen crops afterwards.
  const KEEP = new Set(["P", "H1", "H2", "H3", "H4", "H5", "H6", "UL", "OL", "LI", "DL", "DT", "DD", "TABLE", "THEAD",
    "TBODY", "TFOOT", "TR", "TD", "TH", "CAPTION", "PRE", "CODE", "KBD", "SAMP", "BLOCKQUOTE", "A", "B", "STRONG", "I",
    "EM", "U", "S", "SUB", "SUP", "MARK", "SMALL", "BR", "HR", "FIGURE", "FIGCAPTION"]);
  const SKIP = new Set(["SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE", "HEAD", "META", "LINK", "TITLE", "ALTO-CLIP"]);
  const VISUAL = new Set(["IMG", "SVG", "CANVAS", "VIDEO", "PICTURE", "IFRAME", "OBJECT", "EMBED", "MATH", "INPUT",
    "SELECT", "TEXTAREA", "BUTTON", "METER", "PROGRESS", "AUDIO"]);
  const VISUAL_SEL = ".katex, .katex-display, mjx-container, .MathJax, .MathJax_Display, .MathJax_SVG, .mwe-math-element, [role=img], [role=math]";
  const STYLE_PROPS = ["color", "font-family", "font-size", "font-weight", "font-style", "text-decoration-line",
    "vertical-align", "white-space"];
  const BLOCK_PROPS = ["text-align", "background-color", "margin-left", "padding-left"];

  function extract(sel) {
    const visuals = [];
    const lines = [];
    let line = "";
    const flush = () => { if (line.trim()) lines.push(line.replace(/ +/g, " ").trim()); line = ""; };
    const out = document.createElement("div");
    const base = getComputedStyle(document.body);
    out.setAttribute("style", `font-family:${base.fontFamily};font-size:${base.fontSize};color:${base.color}`);
    const bg = effectiveBackground(document.elementFromPoint(sel.left + 1, sel.top + 1));
    if (bg && !/^rgba?\(255, 255, 255/.test(bg)) out.style.backgroundColor = bg;

    const walk = (node, into, parentCs) => {
      const kids = node.shadowRoot ? node.shadowRoot.childNodes
                 : node.tagName === "SLOT" ? node.assignedNodes({ flatten: true }) : node.childNodes;
      for (const child of kids) {
        if (child.nodeType === Node.TEXT_NODE) { text(child, into); continue; }
        if (child.nodeType !== Node.ELEMENT_NODE || SKIP.has(child.tagName.toUpperCase())) continue;
        const cs = getComputedStyle(child);
        if (cs.display === "none" || cs.visibility === "hidden" || cs.opacity === "0") continue;
        if (cs.display !== "contents") {
          const r = child.getBoundingClientRect();
          const tag = child.tagName.toUpperCase();
          if (!intersects(r, sel)) { if (tag === "BR") continue; if (!hasOverflowingKids(cs)) continue; }
          if (VISUAL.has(tag) || child.matches(VISUAL_SEL) || iconLike(child, cs, r)) {
            const area = intersect(r, sel);
            if (!area || area.width < 2 || area.height < 2) continue;
            const img = document.createElement("img");
            img.setAttribute("width", Math.round(area.width));
            img.setAttribute("height", Math.round(area.height));
            const alt = child.getAttribute("alt") || child.getAttribute("aria-label") ||
                        (child.querySelector && child.querySelector("annotation")?.textContent) || "";
            if (alt) img.setAttribute("alt", alt.trim());
            into.appendChild(img);
            visuals.push({ node: img, rect: area });
            if (isBlock(cs)) flush();
            continue;
          }
        }
        const tag = child.tagName.toUpperCase();
        const block = isBlock(cs) && cs.display !== "table-cell";
        const outTag = KEEP.has(tag) ? tag : (block ? "DIV" : "SPAN");
        const copy = document.createElement(outTag);
        if (tag === "A" && child.href) copy.setAttribute("href", child.href);
        for (const a of ["colspan", "rowspan", "start"]) if (child.hasAttribute(a)) copy.setAttribute(a, child.getAttribute(a));
        const style = styleDiff(cs, parentCs, block, tag);
        if (style) copy.setAttribute("style", style);
        if (tag === "BR") { into.appendChild(copy); flush(); continue; }
        walk(child, copy, cs);
        if (copy.childNodes.length || tag === "HR") into.appendChild(copy);
        if (block) flush();
        if (tag === "TD" || tag === "TH") line += "\t";
      }
    };

    const text = (node, into) => {
      const s = node.data;
      if (!s.trim()) { if (into.childNodes.length) { into.appendChild(document.createTextNode(" ")); line += " "; } return; }
      const range = document.createRange();
      range.selectNodeContents(node);
      const rects = [...range.getClientRects()];
      if (!rects.some((r) => intersects(r, sel))) return;
      let kept = s;
      if (!rects.every((r) => inside(r, sel))) {   // on the edge: keep the words whose centre is inside
        kept = "";
        const parts = s.split(/(\s+)/);
        let at = 0;
        for (const p of parts) {
          if (p && !/^\s+$/.test(p)) {
            range.setStart(node, at);
            range.setEnd(node, at + p.length);
            const wr = range.getBoundingClientRect();
            if (centreIn(wr, sel)) kept += (kept && !/\s$/.test(kept) ? " " : "") + p;
          } else if (kept) kept += p;
          at += p.length;
        }
        kept = kept.replace(/\s+$/, s.match(/\s$/) ? " " : "");
      }
      if (!kept) return;
      into.appendChild(document.createTextNode(kept));
      line += kept;
    };

    walk(document.body, out, base);
    flush();
    return { root: out, visuals, text: lines.join("\n") };
  }

  function styleDiff(cs, parentCs, block, tag) {
    const parts = [];
    for (const p of STYLE_PROPS) {
      const v = cs.getPropertyValue(p);
      if (v !== parentCs.getPropertyValue(p) && !(p === "vertical-align" && v === "baseline") &&
          !(p === "white-space" && !/^pre/.test(v))) parts.push(`${p}:${v}`);
    }
    const bg = cs.backgroundColor;
    if (bg && bg !== "rgba(0, 0, 0, 0)" && bg !== "transparent" && bg !== parentCs.backgroundColor) parts.push(`background-color:${bg}`);
    if (block) {
      if (cs.textAlign !== parentCs.textAlign && !/^(start|left)$/.test(cs.textAlign)) parts.push(`text-align:${cs.textAlign}`);
      if (tag === "BLOCKQUOTE" || parseFloat(cs.borderLeftWidth) >= 2) {
        if (parseFloat(cs.borderLeftWidth) > 0) parts.push(`border-left:${cs.borderLeftWidth} solid ${cs.borderLeftColor}`);
        parts.push(`padding-left:${cs.paddingLeft}`);
      }
    }
    if ((tag === "TD" || tag === "TH" || tag === "TABLE") && parseFloat(cs.borderTopWidth) > 0) {
      parts.push(`border:${cs.borderTopWidth} solid ${cs.borderTopColor}`, `padding:${cs.padding || "2px 6px"}`);
    }
    if (tag === "TABLE") parts.push("border-collapse:collapse");
    return parts.join(";");
  }

  const isBlock = (cs) => !/^inline/.test(cs.display) && cs.display !== "contents";
  const hasOverflowingKids = (cs) => cs.overflow === "visible" && cs.position !== "static";
  function iconLike(node, cs, r) {                 // background-image pictures with no text of their own
    return cs.backgroundImage && cs.backgroundImage !== "none" && /url\(/.test(cs.backgroundImage) &&
           !node.textContent.trim() && r.width >= 8 && r.height >= 8;
  }
  function effectiveBackground(node) {
    for (let n = node; n && n.nodeType === 1; n = n.parentElement) {
      const bg = getComputedStyle(n).backgroundColor;
      if (bg && bg !== "rgba(0, 0, 0, 0)" && bg !== "transparent") return bg;
    }
    return null;
  }

  // Click-to-clip on a web page: the nearest sensible block under the cursor.
  function blockRect(target) {
    const vw = window.innerWidth, vh = window.innerHeight;
    for (let n = target; n && n !== document.body && n !== document.documentElement; n = n.parentElement) {
      const r = n.getBoundingClientRect();
      if (r.width * r.height > vw * vh * 0.85) break;
      const cs = getComputedStyle(n);
      const visual = VISUAL.has(n.tagName.toUpperCase()) || n.matches(VISUAL_SEL);
      if (/^table-(cell|row|row-group|header-group|footer-group)$|^list-item$/.test(cs.display)) continue;
      if ((visual || isBlock(cs)) && r.width >= 24 && r.height >= 16) return clampToViewport(r);
    }
    return null;
  }

  // ---- PDF reader ----------------------------------------------------------------------------
  function pdfPageRect(target) {
    const page = target && target.closest && target.closest(".page");
    if (!page) return null;
    const wrap = page.querySelector(".canvasWrapper") || page;
    return clampToViewport(wrap.getBoundingClientRect());
  }

  function pdfTarget(sel) {
    const app = globalThis.PDFViewerApplication;
    let best = null;
    for (const div of document.querySelectorAll("#viewer .page")) {
      const wrap = div.querySelector(".canvasWrapper") || div;
      const r = wrap.getBoundingClientRect();
      const a = intersect(r, sel);
      if (a && (!best || a.width * a.height > best.area)) best = { div, r, a, area: a.width * a.height };
    }
    if (!best) throw new Error("the box isn't over a page");
    const n = parseInt(best.div.getAttribute("data-page-number"), 10);
    const view = app.pdfViewer.getPageView(n - 1);
    const vp = view.viewport;
    const p1 = vp.convertToPdfPoint(best.a.left - best.r.left, best.a.top - best.r.top);
    const p2 = vp.convertToPdfPoint(best.a.right - best.r.left, best.a.bottom - best.r.top);
    const pdfRect = [Math.min(p1[0], p2[0]), Math.min(p1[1], p2[1]), Math.max(p1[0], p2[0]), Math.max(p1[1], p2[1])];
    return { app, n, view, pdfRect, screen: best.a };
  }

  async function pdfClip(sel, mode) {
    const { app, n, view, pdfRect, screen } = pdfTarget(sel);
    const page = view.pdfPage || await app.pdfDocument.getPage(n);
    const rotation = view.viewport.rotation;
    const v1 = page.getViewport({ scale: 1, rotation });
    const [a, b] = v1.convertToViewportPoint(pdfRect[0], pdfRect[1]);
    const [c, d] = v1.convertToViewportPoint(pdfRect[2], pdfRect[3]);
    const box1 = { x: Math.min(a, c), y: Math.min(b, d), w: Math.abs(c - a), h: Math.abs(d - b) };
    // Same pixel size as the box on screen (Chrome drops DPI tags, so pixels decide the pasted size).
    const scale = (screen.width * devicePixelRatio) / box1.w;
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(box1.w * scale));
    canvas.height = Math.max(1, Math.round(box1.h * scale));
    const ctx = canvas.getContext("2d");
    await page.render({ canvasContext: ctx, viewport: page.getViewport({ scale, rotation }), background: "white",
                        transform: [1, 0, 0, 1, -box1.x * scale, -box1.y * scale] }).promise;
    const png = await new Promise((r) => canvas.toBlob(r, "image/png"));
    const pngUri = await blobToDataUri(png);
    const w = Math.round(screen.width), h = Math.round(screen.height);
    const lines = await pdfLines(page, pdfRect);
    const text = lines.map((l) => l.text).join("\n");
    const html = mode === "text" && text.trim() ? pdfTextHtml(lines) : imgTag(pngUri, w, h);
    const summary = mode === "text" && text.trim() ? `Copied text from page ${n} · Ctrl+V`
                                                   : `Copied exact clip of page ${n} · Ctrl+V`;
    const title = (app._title || document.title || "document").replace(/\.pdf$/i, "");
    const save = () => savePdfCrop(app, n, pdfRect, `${fileStem(title)} - p${n} clip.pdf`);
    return { png, html, text, summary, save };
  }

  // Text items whose centre lies inside the box, grouped into lines (top to bottom, left to right).
  async function pdfLines(page, [x1, y1, x2, y2]) {
    const content = await page.getTextContent();
    const items = [];
    for (const it of content.items) {
      if (!it.str || !it.transform) continue;
      const [, , , dy, x, y] = it.transform;
      const hgt = it.height || Math.abs(dy) || 10;
      const cx = x + (it.width || 0) / 2, cy = y + hgt / 2;
      if (cx < x1 || cx > x2 || cy < y1 || cy > y2) continue;
      items.push({ str: it.str, x, y, w: it.width || 0, h: hgt, bold: isBold(page, it.fontName) });
    }
    items.sort((p, q) => (Math.abs(q.y - p.y) > Math.min(p.h, q.h) * 0.5 ? q.y - p.y : p.x - q.x));
    const lines = [];
    for (const it of items) {
      const last = lines[lines.length - 1];
      if (last && Math.abs(last.y - it.y) <= Math.min(last.h, it.h) * 0.5) {
        const gap = it.x - last.end;
        const sep = gap > it.h * 0.15 && !/\s$/.test(last.text) && !/^\s/.test(it.str) ? " " : "";
        last.text += sep + it.str;
        last.parts.push({ s: sep + it.str, bold: it.bold });
        last.end = it.x + it.w;
        last.h = Math.max(last.h, it.h);
      } else {
        lines.push({ y: it.y, h: it.h, end: it.x + it.w, text: it.str, parts: [{ s: it.str, bold: it.bold }] });
      }
    }
    return lines;
  }

  function isBold(page, id) {                      // font objects are known once the page has rendered
    try { const f = page.commonObjs.has(id) && page.commonObjs.get(id); return !!(f && (f.bold || f.black)); }
    catch (e) { return false; }
  }

  function pdfTextHtml(lines) {
    const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    const out = [];
    let para = [], prev = null;
    const flushPara = () => {
      if (para.length) out.push(para.map((l, i) => `<p style="margin:0 0 ${i === para.length - 1 ? ".6em" : "0"}">${l}</p>`).join(""));
      para = [];
    };
    for (const l of lines) {
      if (prev && prev.y - l.y > Math.max(prev.h, l.h) * 1.8) flushPara();
      const pt = Math.max(7, Math.min(40, Math.round(l.h)));
      para.push(`<span style="font-size:${pt}pt">` +
                l.parts.map((p) => (p.bold ? `<b>${esc(p.s)}</b>` : esc(p.s))).join("") + "</span>");
      prev = l;
    }
    flushPara();
    return `<div style="font-family:Calibri,Arial,sans-serif">${out.join("")}</div>`;
  }

  // A one-page PDF holding only the box: the original vectors and text, cropped (pdf-lib).
  async function savePdfCrop(app, n, [x1, y1, x2, y2], filename) {
    if (!globalThis.PDFLib) {
      await new Promise((resolve, reject) => {
        const s = document.createElement("script");
        s.src = chrome.runtime.getURL("vendor/pdf-lib/pdf-lib.min.js");
        s.onload = resolve; s.onerror = () => reject(new Error("pdf-lib failed to load"));
        document.head.appendChild(s);
      });
    }
    const { PDFDocument } = globalThis.PDFLib;
    const src = await PDFDocument.load(await app.pdfDocument.getData(), { ignoreEncryption: true });
    const out = await PDFDocument.create();
    const [copied] = await out.copyPages(src, [n - 1]);
    copied.setMediaBox(x1, y1, x2 - x1, y2 - y1);
    copied.setCropBox(x1, y1, x2 - x1, y2 - y1);
    out.addPage(copied);
    return saveBlob(new Blob([await out.save()], { type: "application/pdf" }), filename);
  }

  // ---- helpers -------------------------------------------------------------------------------
  function el(tag, cls) { const e = document.createElement(tag); if (cls) e.className = cls; return e; }
  function rectFrom(p, q) {
    const left = Math.min(p.x, q.x), top = Math.min(p.y, q.y);
    return DOMRect.fromRect({ x: left, y: top, width: Math.abs(q.x - p.x), height: Math.abs(q.y - p.y) });
  }
  function clampToViewport(r) {
    const left = Math.max(0, r.left), top = Math.max(0, r.top);
    const right = Math.min(window.innerWidth, r.right), bottom = Math.min(window.innerHeight, r.bottom);
    return right > left && bottom > top ? DOMRect.fromRect({ x: left, y: top, width: right - left, height: bottom - top }) : null;
  }
  const intersects = (r, s) => r.right > s.left && r.left < s.right && r.bottom > s.top && r.top < s.bottom;
  const inside = (r, s) => r.left >= s.left - 1 && r.right <= s.right + 1 && r.top >= s.top - 1 && r.bottom <= s.bottom + 1;
  const centreIn = (r, s) => { const x = r.left + r.width / 2, y = r.top + r.height / 2; return x >= s.left && x <= s.right && y >= s.top && y <= s.bottom; };
  function intersect(r, s) {
    const left = Math.max(r.left, s.left), top = Math.max(r.top, s.top);
    const right = Math.min(r.right, s.right), bottom = Math.min(r.bottom, s.bottom);
    return right > left && bottom > top ? DOMRect.fromRect({ x: left, y: top, width: right - left, height: bottom - top }) : null;
  }
  const imgTag = (src, w, h) => `<img src="${src}" width="${w}" height="${h}">`;
  const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
  async function blobToDataUri(blob) {
    return `data:${blob.type};base64,` + new Uint8Array(await blob.arrayBuffer()).toBase64();
  }
  function fileStem(title) {
    return (title || "clip").replace(/[<>:"/\\|?*\x00-\x1f]/g, "_").replace(/\s+/g, " ").trim().slice(0, 120) || "clip";
  }
  async function saveBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    try {
      const r = await chrome.runtime.sendMessage({ type: "clip-save", url, filename });
      if (r && r.error && !/cancel/i.test(r.error)) throw new Error(r.error);
    } finally {
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    }
  }

  globalThis.altoClip = { start, extract };
})();
