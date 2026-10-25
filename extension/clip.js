// Alt+L: drag a box (or click a block) and the content under it goes to the clipboard, ready for Ctrl+V.
// Hold Shift to add several boxes; they are copied together, in page order.
//   Text mode (default): real text with its formatting; images, diagrams, formulas and other visuals come along as exact
//               crops of the screen. Also puts plain text and a PNG of the whole box on the clipboard.
//   Image mode: one exact picture of the box, at the screen's own pixel size (pastes like Win+Shift+S).
// In the built-in PDF reader the picture is re-rendered from the PDF at screen resolution, the text comes from the PDF,
// and "Save…" writes a cropped vector PDF of just the box.
// Injected into web pages by capture.js; included by the PDF reader (vendor/pdfjs/web/viewer.html).
(() => {
  if (globalThis.altoClip) return;

  const isPdf = () => !!(globalThis.PDFViewerApplication && globalThis.PDFViewerApplication.pdfDocument);
  const MODE_KEY = "clipMode";                     // { web: "text" | "image", pdf: "text" | "image" }
  const DEFAULT_MODES = { web: "text", pdf: "text" };

  let active = null;                               // the open overlay, if any
  let lastToast = null;                            // removed when a new clip starts, so it never ends up in the shot

  // ---- overlay -------------------------------------------------------------------------------
  const CSS = `
    :host { all: initial; }
    .layer { position: fixed; inset: 0; z-index: 2147483647; cursor: crosshair; background: rgba(15,23,42,.28); }
    .layer.has-box { background: transparent; }
    .box { position: fixed; border: 2px solid #fff; outline: 1px solid rgba(37,99,235,.9);
           box-shadow: 0 0 0 100vmax rgba(15,23,42,.38); pointer-events: none; display: none; }
    .kept { position: fixed; border: 2px solid #22c55e; background: rgba(34,197,94,.14); pointer-events: none;
            align-items: flex-start; padding: 4px 6px; box-sizing: border-box;
            font: 700 12px/1 system-ui, sans-serif; color: #fff; text-shadow: 0 0 3px #000; }
    .box.plain { box-shadow: none; }
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
    if (lastToast) { lastToast.remove(); lastToast = null; }
    const modes = await loadModes();
    const kind = isPdf() ? "pdf" : "web";
    let mode = modes[kind];
    const { host, root } = makeHost();
    const layer = el("div", "layer"), box = el("div", "box"), hover = el("div", "hover"), size = el("div", "size");
    const keptLayer = el("div");
    const bar = el("div", "bar");
    const textBtn = el("button"), imgBtn = el("button");
    textBtn.innerHTML = "Editable text<u>T</u>";
    imgBtn.innerHTML = "Exact image<u>I</u>";
    const hint = el("span", "hint");
    bar.append(textBtn, imgBtn, hint);
    root.append(layer, keptLayer, hover, box, size, bar);
    const paint = () => { textBtn.classList.toggle("on", mode === "text"); imgBtn.classList.toggle("on", mode === "image"); };
    const setMode = (m) => {
      mode = m; paint();
      modes[kind] = m;
      try { chrome.storage.local.set({ [MODE_KEY]: modes }); } catch (e) { /* storage unavailable */ }
    };
    paint();

    // Boxes kept with Shift. Stored scroll-independently (page coordinates, or PDF page + PDF rectangle)
    // so you can scroll between them.
    const boxes = [];
    const scroller = kind === "pdf" ? document.getElementById("viewerContainer") : window;
    const toBox = (r) => kind === "pdf" ? pdfTarget(r)
      : { page: DOMRect.fromRect({ x: r.left + scrollX, y: r.top + scrollY, width: r.width, height: r.height }) };
    const onScreen = (b) => kind === "pdf" ? pdfScreenRect(b)
      : DOMRect.fromRect({ x: b.page.left - scrollX, y: b.page.top - scrollY, width: b.page.width, height: b.page.height });
    const redraw = () => {
      keptLayer.replaceChildren(...boxes.map((b, i) => {
        const k = el("div", "kept");
        show(k, onScreen(b));
        k.textContent = String(i + 1);
        return k;
      }));
      layer.classList.remove("has-box");           // with kept boxes the layer dims, not the drag box
      hint.textContent = boxes.length
        ? `${plural(boxes.length, "box")} · Shift+drag to add more · Enter to copy · ⌫ undo · Esc`
        : (kind === "pdf" ? "Drag a box · click = whole page" : "Drag a box · click a block") + " · Shift = several · Esc";
    };

    let startPt = null, dragging = false, picked = null;
    const close = () => {
      host.remove();
      window.removeEventListener("keydown", onKey, true);
      scroller.removeEventListener("scroll", redraw);
      active = null;
    };
    active = { close };
    const done = () => {
      if (!boxes.length) return;
      close();
      finish(boxes.slice(), mode, kind);
    };

    const pick = (x, y) => {                       // block under the cursor, for click-to-clip
      host.style.pointerEvents = "none";
      layer.style.pointerEvents = "none";
      const target = document.elementFromPoint(x, y);
      host.style.pointerEvents = "";
      layer.style.pointerEvents = "";
      return kind === "pdf" ? pdfPageRect(target) : blockRect(target);
    };
    function show(node, r) {
      if (!r) { node.style.display = "none"; return; }
      Object.assign(node.style, { display: "flex", left: r.left + "px", top: r.top + "px",
                                  width: r.width + "px", height: r.height + "px" });
    }

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
      if (!boxes.length) layer.classList.add("has-box");
      box.classList.toggle("plain", boxes.length > 0);
      const r = rectFrom(startPt, { x: e.clientX, y: e.clientY });
      show(box, r);
      Object.assign(size.style, { display: "block", left: r.left + "px", top: Math.max(0, r.top - 22) + "px" });
      size.textContent = `${Math.round(r.width)} × ${Math.round(r.height)}`;
    });
    layer.addEventListener("pointerup", (e) => {
      if (!startPt) return;
      const r = dragging ? rectFrom(startPt, { x: e.clientX, y: e.clientY }) : picked;
      startPt = null;
      box.style.display = size.style.display = "none";
      if (r && r.width >= 4 && r.height >= 4) {
        try { boxes.push(toBox(r)); } catch (err) { /* PDF box outside every page */ }
      }
      redraw();
      if (!(e.shiftKey || e.ctrlKey)) done();
    });
    layer.addEventListener("wheel", (e) => {
      scroller.scrollBy(e.deltaX, e.deltaY);
      e.preventDefault();
    }, { passive: false });
    scroller.addEventListener("scroll", redraw, { passive: true });
    layer.addEventListener("contextmenu", (e) => { e.preventDefault(); close(); });
    textBtn.addEventListener("click", () => setMode("text"));
    imgBtn.addEventListener("click", () => setMode("image"));
    bar.addEventListener("pointerdown", (e) => e.stopPropagation());
    redraw();

    function onKey(e) {
      const k = e.key.toLowerCase();
      if (k === "escape") close();
      else if (k === "enter") done();
      else if (k === "backspace") { boxes.pop(); redraw(); }
      else if (k === "t") setMode("text");
      else if (k === "i") setMode("image");
      else return;
      e.preventDefault();
      e.stopPropagation();
    }
    window.addEventListener("keydown", onKey, true);
  }

  // ---- after the boxes are chosen ------------------------------------------------------------
  // The clipboard write starts right away (inside the gesture) with promises for each format.
  function finish(boxes, mode, kind) {
    const work = kind === "pdf" ? pdfClip(boxes, mode) : webClip(boxes, mode);
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
    if (lastToast) lastToast.remove();
    const { host, root } = makeHost();
    lastToast = host;
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
  // Boxes are in page coordinates. Text comes from the DOM; pixels from screenshots: one if every box is
  // in view, otherwise the page is scrolled to each box in turn (then put back).
  async function webClip(boxes, mode) {
    boxes = boxes.slice().sort((a, b) => a.page.top - b.page.top || a.page.left - b.page.left);
    const sx = scrollX, sy = scrollY;
    const client = (p, ox = sx, oy = sy) => DOMRect.fromRect({ x: p.left - ox, y: p.top - oy, width: p.width, height: p.height });
    const plan = mode === "text" ? extract(boxes.map((b) => client(b.page))) : null;
    if (plan) for (const v of plan.visuals) v.page = DOMRect.fromRect({ x: v.rect.left + sx, y: v.rect.top + sy, width: v.rect.width, height: v.rect.height });

    const shots = [];
    const inView = (p, ox, oy) => p.top - oy >= 0 && p.bottom - oy <= innerHeight && p.left - ox >= 0 && p.right - ox <= innerWidth;
    const shotFor = async (p) => {
      let s = shots.find((t) => inView(p, t.x, t.y));
      if (s) return s;
      if (shots.length || !inView(p, sx, sy)) {
        window.scrollTo(sx, Math.max(0, p.top - 8));
        if (shots.length) await new Promise((r) => setTimeout(r, 550));   // captureVisibleTab: max 2 per second
      }
      const img = await screenshot();
      s = { img, x: scrollX, y: scrollY, ratio: img.width / innerWidth };
      shots.push(s);
      return s;
    };
    const crop = async (p) => { const s = await shotFor(p); return cropPng(s.img, client(p, s.x, s.y), s.ratio); };
    try {
      const pieces = [];
      for (const b of boxes) pieces.push(await crop(b.page));
      if (plan) for (const v of plan.visuals) v.blob = await crop(v.page);
      const png = await stack(pieces, shots[0].ratio);
      let html, text = "", summary;
      if (plan) {
        for (const v of plan.visuals) v.node.src = await blobToDataUri(v.blob);
        html = plan.root.outerHTML;
        text = plan.text;
        const pics = plan.visuals.length ? " + " + plural(plan.visuals.length, "picture") : "";
        summary = text.trim() ? `Copied text${pics}${boxes.length > 1 ? ` from ${boxes.length} boxes` : ""} · Ctrl+V`
                              : "Copied picture · Ctrl+V";
        if (!text.trim() && !plan.visuals.length) html = imgTag(await blobToDataUri(png), Math.round(boxes[0].page.width), Math.round(boxes[0].page.height));
      } else {
        summary = `Copied exact image${boxes.length > 1 ? ` of ${boxes.length} boxes` : ""} · Ctrl+V`;
      }
      const save = () => saveBlob(png, fileStem(document.title) + " clip.png");
      return { png, html, text, summary, save };
    } finally {
      if (scrollX !== sx || scrollY !== sy) window.scrollTo(sx, sy);
    }
  }

  // Several crops one above the other on white, for the image flavour of a multi-box clip.
  async function stack(blobs, ratio) {
    if (blobs.length === 1) return blobs[0];
    const imgs = await Promise.all(blobs.map((b) => createImageBitmap(b)));
    const gap = Math.round(12 * (ratio || 1));
    const c = new OffscreenCanvas(Math.max(...imgs.map((i) => i.width)),
                                  imgs.reduce((h, i) => h + i.height, 0) + gap * (imgs.length - 1));
    const g = c.getContext("2d");
    g.fillStyle = "#fff";
    g.fillRect(0, 0, c.width, c.height);
    let y = 0;
    for (const i of imgs) { g.drawImage(i, 0, y); y += i.height + gap; }
    return c.convertToBlob({ type: "image/png" });
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
    const sels = [].concat(sel);                   // one box or several (client coordinates)
    const hit = (r) => sels.some((s) => intersects(r, s));
    const within = (r) => sels.some((s) => inside(r, s));
    const centred = (r) => sels.some((s) => centreIn(r, s));
    const clipArea = (r) => {                      // part of r inside the boxes (their bounding box if several)
      const parts = sels.map((s) => intersect(r, s)).filter(Boolean);
      if (!parts.length) return null;
      const left = Math.min(...parts.map((q) => q.left)), top = Math.min(...parts.map((q) => q.top));
      return DOMRect.fromRect({ x: left, y: top, width: Math.max(...parts.map((q) => q.right)) - left,
                                height: Math.max(...parts.map((q) => q.bottom)) - top });
    };
    const visuals = [];
    const lines = [];
    let line = "";
    const flush = () => { if (line.trim()) lines.push(line.replace(/ +/g, " ").trim()); line = ""; };
    const out = document.createElement("div");
    const base = getComputedStyle(document.body);
    out.setAttribute("style", `font-family:${base.fontFamily};font-size:${base.fontSize};color:${base.color}`);
    const bg = effectiveBackground(document.elementFromPoint(sels[0].left + 1, sels[0].top + 1));
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
          if (!hit(r)) { if (tag === "BR") continue; if (!hasOverflowingKids(cs)) continue; }
          if (VISUAL.has(tag) || child.matches(VISUAL_SEL) || iconLike(child, cs, r)) {
            const area = clipArea(r);
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
      if (!rects.some(hit)) return;
      let kept = s;
      if (!rects.every(within)) {   // on the edge: keep the words whose centre is inside
        kept = "";
        const parts = s.split(/(\s+)/);
        let at = 0;
        for (const p of parts) {
          if (p && !/^\s+$/.test(p)) {
            range.setStart(node, at);
            range.setEnd(node, at + p.length);
            const wr = range.getBoundingClientRect();
            if (centred(wr)) kept += (kept && !/\s$/.test(kept) ? " " : "") + p;
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
    const vp = app.pdfViewer.getPageView(n - 1).viewport;
    const p1 = vp.convertToPdfPoint(best.a.left - best.r.left, best.a.top - best.r.top);
    const p2 = vp.convertToPdfPoint(best.a.right - best.r.left, best.a.bottom - best.r.top);
    const pdfRect = [Math.min(p1[0], p2[0]), Math.min(p1[1], p2[1]), Math.max(p1[0], p2[0]), Math.max(p1[1], p2[1])];
    return { n, pdfRect, cssWidth: best.a.width };
  }

  // Where a kept PDF box is on screen now (after scrolling or zooming).
  function pdfScreenRect({ n, pdfRect }) {
    const view = globalThis.PDFViewerApplication.pdfViewer.getPageView(n - 1);
    const wrap = view && (view.div.querySelector(".canvasWrapper") || view.div);
    if (!wrap) return null;
    const r = wrap.getBoundingClientRect();
    const [a, b] = view.viewport.convertToViewportPoint(pdfRect[0], pdfRect[1]);
    const [c, d] = view.viewport.convertToViewportPoint(pdfRect[2], pdfRect[3]);
    return DOMRect.fromRect({ x: r.left + Math.min(a, c), y: r.top + Math.min(b, d), width: Math.abs(c - a), height: Math.abs(d - b) });
  }

  async function pdfClip(boxes, mode) {
    const app = globalThis.PDFViewerApplication;
    boxes = boxes.slice().sort((a, b) => a.n - b.n || b.pdfRect[3] - a.pdfRect[3] || a.pdfRect[0] - b.pdfRect[0]);
    const pieces = [], htmls = [], texts = [];
    for (const { n, pdfRect, cssWidth } of boxes) {
      const page = await app.pdfDocument.getPage(n);
      const rotation = app.pdfViewer.getPageView(n - 1).viewport.rotation;
      const v1 = page.getViewport({ scale: 1, rotation });
      const [a, b] = v1.convertToViewportPoint(pdfRect[0], pdfRect[1]);
      const [c, d] = v1.convertToViewportPoint(pdfRect[2], pdfRect[3]);
      const box1 = { x: Math.min(a, c), y: Math.min(b, d), w: Math.abs(c - a), h: Math.abs(d - b) };
      // Same pixel size as the box on screen (Chrome drops DPI tags, so pixels decide the pasted size).
      const scale = (cssWidth * devicePixelRatio) / box1.w;
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(box1.w * scale));
      canvas.height = Math.max(1, Math.round(box1.h * scale));
      await page.render({ canvasContext: canvas.getContext("2d"), viewport: page.getViewport({ scale, rotation }),
                          background: "white", transform: [1, 0, 0, 1, -box1.x * scale, -box1.y * scale] }).promise;
      pieces.push(await new Promise((r) => canvas.toBlob(r, "image/png")));
      const lines = await pdfLines(page, pdfRect);
      texts.push(lines.map((l) => l.text).join("\n"));
      htmls.push(pdfTextHtml(lines));
    }
    const png = await stack(pieces, devicePixelRatio);
    const text = texts.filter((t) => t.trim()).join("\n\n");
    const pages = [...new Set(boxes.map((b) => b.n))];
    const where = pages.length === 1 ? `page ${pages[0]}` : `pages ${pages.join(", ")}`;
    const html = text.trim() ? htmls.join("") : `<img src="${await blobToDataUri(png)}">`;
    const summary = mode === "text" && text.trim() ? `Copied text from ${where} · Ctrl+V` : `Copied exact clip of ${where} · Ctrl+V`;
    const title = (document.title || "document").replace(/\.pdf$/i, "");
    const save = () => savePdfCrop(app, boxes, `${fileStem(title)} - p${pages.join("+")} clip.pdf`);
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

  // A PDF holding only the boxes, one per page: the original vectors and text, cropped (pdf-lib).
  async function savePdfCrop(app, boxes, filename) {
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
    for (const { n, pdfRect: [x1, y1, x2, y2] } of boxes) {
      const [copied] = await out.copyPages(src, [n - 1]);
      copied.setMediaBox(x1, y1, x2 - x1, y2 - y1);
      copied.setCropBox(x1, y1, x2 - x1, y2 - y1);
      out.addPage(copied);
    }
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
