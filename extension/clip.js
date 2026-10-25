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
    "vertical-align", "white-space", "line-height", "letter-spacing"];
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
    // "Designed" blocks that Word/OneNote can't lay out (text over a picture, side-by-side rows such as nav bars
    // and cards) are pasted as exact pictures instead, when they sit mostly inside the boxes.
    const vw = innerWidth, vh = innerHeight;
    const designBlock = (node, cs, r) => {
      const a = clipArea(r);
      if (!a) return false;
      if (cs.float !== "none" && r.width < vw * 0.6 && node.querySelector("img, svg, canvas, video")) return true;   // floated figure + caption
      if (r.width * r.height > vw * vh * 0.9 || a.width * a.height < r.width * r.height * 0.6) return false;
      if (r.width < 24 || r.height < 16 || !node.textContent.trim()) return false;
      if (/url\(|gradient\(/.test(cs.backgroundImage)) return true;
      const area = r.width * r.height;
      for (const m of node.querySelectorAll("img, video, canvas, picture, svg")) {
        const mr = m.getBoundingClientRect();
        if (mr.width * mr.height > area * 0.3) return true;                       // text laid over a big picture
      }
      if (/^(inline-)?(flex|grid)$/.test(cs.display)) {
        const kids = [...node.children].map((k) => k.getBoundingClientRect()).filter((k) => k.width > 0 && k.height > 0);
        for (let i = 1; i < kids.length; i++) {
          const p = kids[i - 1], k = kids[i];
          if (k.left >= p.right - 2 && k.top < p.bottom && k.bottom > p.top) return true;   // side by side
        }
      }
      return false;
    };
    // Text drawn on top of a picture (a hero over a background video, a caption over a photo...) can't be
    // rebuilt either. Sample the stack of elements at points across the boxes; where text sits above an image,
    // video, canvas or background picture, the smallest element holding both becomes an exact picture.
    const layered = new Set();
    const isPicture = (el) => {
      if (el === document.body || el === document.documentElement) return false;
      if (/^(IMG|VIDEO|CANVAS|PICTURE|IFRAME|SVG|EMBED|OBJECT)$/i.test(el.tagName)) return true;
      const c = getComputedStyle(el);
      return /url\(|gradient\(/.test(c.backgroundImage) && !/^repeat/.test(c.backgroundRepeat);   // not a tiled texture
    };
    const ownText = (el) => [...el.childNodes].some((n) => n.nodeType === Node.TEXT_NODE && n.data.trim());
    for (const s of sels) {
      const step = Math.max(16, Math.sqrt((s.width * s.height) / 1500));
      for (let y = s.top + step / 2; y < s.bottom; y += step) {
        for (let x = s.left + step / 2; x < s.right; x += step) {
          const stack = document.elementsFromPoint(x, y);
          const t = stack.findIndex(ownText);
          if (t < 0) continue;
          const m = stack.findIndex((el, i) => i > t && isPicture(el));
          if (m < 0) continue;
          let common = stack[m];
          while (common && !common.contains(stack[t])) common = common.parentElement;
          if (common && common !== document.body && common !== document.documentElement) layered.add(common);
        }
      }
    }
    const visuals = [];
    const lines = [];
    let line = "";
    const flush = () => { if (line.trim()) lines.push(line.replace(/ +/g, " ").trim()); line = ""; };
    const out = document.createElement("div");
    const base = getComputedStyle(document.body);
    // the box's own width, so lines wrap where they did on screen
    out.setAttribute("style", `width:${Math.round(Math.max(...sels.map((s) => s.width)))}px;max-width:100%;` +
                              `font-family:${base.fontFamily};font-size:${base.fontSize};color:${base.color};line-height:${base.lineHeight}`);
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
          if (VISUAL.has(tag) || child.matches(VISUAL_SEL) || iconLike(child, cs, r) || layered.has(child) || designBlock(child, cs, r)) {
            const area = clipArea(r);
            if (!area || area.width < 2 || area.height < 2) continue;
            const img = document.createElement("img");
            img.setAttribute("width", Math.round(area.width));
            img.setAttribute("height", Math.round(area.height));
            const alt = child.getAttribute("alt") || child.getAttribute("aria-label") ||
                        (child.querySelector && child.querySelector("annotation")?.textContent) || "";
            if (alt) img.setAttribute("alt", alt.trim());
            if (cs.float === "left" || cs.float === "right") {   // text wraps around it, as on the page
              img.setAttribute("align", cs.float);
              img.setAttribute("style", `float:${cs.float};margin:${cs.marginTop} ${cs.marginRight} ${cs.marginBottom} ${cs.marginLeft}`);
            }
            into.appendChild(img);
            visuals.push({ node: img, rect: area });
            if (isBlock(cs)) flush();
            if (!VISUAL.has(tag) && child.innerText && child.innerText.trim()) {   // pictured text still goes in plain text
              flush();
              for (const l of child.innerText.split("\n")) { line = l; flush(); }
            }
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
      const rich = await pdfRich(page, pdfRect, { canvas, box1, scale, v1 });
      texts.push(rich.text);
      htmls.push(rich.html);
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

  // Rebuilds the text inside a PDF box as formatted HTML, the way PyMuPDF / pdfplumber reconstruct layout:
  // items -> lines (same baseline) -> paragraphs (wrapped lines joined; split on vertical gaps, size changes
  // and short lines). Each run keeps its real font family, size, bold/italic (PDF.js font objects) and colour
  // (read from the rendered glyph pixels, since PDF.js text content has no colour). Paragraphs keep their
  // indentation, centring and spacing in points.
  async function pdfRich(page, [x1, y1, x2, y2], raster) {
    const content = await page.getTextContent();
    const ctx = raster.canvas.getContext("2d", { willReadFrequently: true });
    const items = [];
    for (const it of content.items) {
      if (!it.str || !it.transform) continue;
      const [a, b, c, d, x, y] = it.transform;
      const size = Math.hypot(c, d) || it.height || 10;
      const w = it.width || 0;
      const cx = x + w / 2, cy = y + size * 0.35;
      if (cx < x1 || cx > x2 || cy < y1 || cy > y2 || Math.abs(b) > Math.abs(a) * 0.1) continue;   // skip rotated text
      const font = fontInfo(page, it.fontName, content.styles[it.fontName]);
      items.push({ str: it.str, x, y, w, size, ...font, color: glyphColor(ctx, raster, x, y - size * 0.2, x + w, y + size * 0.8) });
    }
    if (!items.length) return { text: "", html: "" };

    // lines: same baseline (within a third of the size), left to right
    items.sort((p, q) => (Math.abs(q.y - p.y) > Math.min(p.size, q.size) * 0.35 ? q.y - p.y : p.x - q.x));
    const lines = [];
    for (const it of items) {
      const last = lines[lines.length - 1];
      if (last && Math.abs(last.y - it.y) <= Math.min(last.first, it.size) * 0.35) {
        const gap = it.x - last.end;
        if (gap > it.size * 0.15 && !/\s$/.test(last.runs[last.runs.length - 1].s) && !/^\s/.test(it.str)) {
          addRun(last.runs, " ", it);
        }
        addRun(last.runs, it.str, it);
        last.end = Math.max(last.end, it.x + it.w);
      } else {
        lines.push({ y: it.y, x: it.x, end: it.x + it.w, first: it.size, runs: [{ s: it.str, ...styleOf(it) }] });
      }
    }
    for (const l of lines) {
      l.text = l.runs.map((r) => r.s).join("");
      l.size = mostCommon(l.runs.filter((r) => r.s.trim()).map((r) => [r.size, r.s.length])) || 10;   // a 12pt colon doesn't make a 12pt line
    }

    // paragraphs
    const left = Math.min(...lines.map((l) => l.x)), right = Math.max(...lines.map((l) => l.end));
    const width = Math.max(1, right - left);
    const centred = (l) => {
      const lm = l.x - x1, rm = x2 - l.end;
      return l.end - l.x < width * 0.85 && lm > l.size && Math.abs(lm - rm) < Math.max(l.size * 1.5, (x2 - x1) * 0.06);
    };
    const paras = [];
    for (const l of lines) {
      const p = paras[paras.length - 1];
      const prev = p && p.lines[p.lines.length - 1];
      const joins = prev &&
        prev.y - l.y < Math.max(prev.size, l.size) * 1.45 &&            // normal line spacing
        Math.abs(prev.size - l.size) < 1 &&                            // same size
        prev.end > right - Math.max(prev.size * 3, width * 0.12) &&   // previous line ran to the right edge
        Math.abs(l.x - p.lines[0].x) < prev.size * 2.5 &&              // same left edge (or first-line indent)
        centred(prev) === centred(l);
      if (joins) {
        const lastRun = p.runs[p.runs.length - 1];
        if (/[A-Za-z]-$/.test(lastRun.s) && /^[a-z]/.test(l.text)) lastRun.s = lastRun.s.slice(0, -1);   // re-join hyphenated words
        else if (!/\s$/.test(lastRun.s)) p.runs.push({ ...lastRun, s: " " });
        for (const r of l.runs) mergeRun(p.runs, r);
        p.lines.push(l);
      } else {
        if (p) p.after = Math.max(0, prev.y - l.y - l.size * 1.2);   // extra space below the previous paragraph
        paras.push({ lines: [l], runs: l.runs.map((r) => ({ ...r })), indent: l.x - left, centred: centred(l), after: 0 });
      }
    }

    // HTML: the most common family/size/colour go on the wrapper; runs only state differences
    const common = (key) => mostCommon(paras.flatMap((p) => p.runs.filter((r) => r.s.trim()).map((r) => [r[key], r.s.length])));
    const base = { family: common("family"), size: common("size"), color: common("color") };
    const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    const html = paras.map((p) => {
      const style = [`margin:0 0 ${round1(Math.min(p.after, 36))}pt ${p.centred ? 0 : round1(p.indent)}pt`];
      if (p.centred) style.push("text-align:center");
      const body = p.runs.map((r) => {
        const s = [];
        if (r.family !== base.family) s.push(`font-family:${cssFamily(r.family)}`);
        if (r.size !== base.size) s.push(`font-size:${r.size}pt`);
        if (r.color !== base.color) s.push(`color:${r.color}`);
        if (r.bold) s.push("font-weight:bold");
        if (r.italic) s.push("font-style:italic");
        return s.length ? `<span style="${s.join(";")}">${esc(r.s)}</span>` : esc(r.s);
      }).join("");
      return `<p style="${style.join(";")}">${body}</p>`;
    }).join("");
    return {
      text: paras.map((p) => (p.centred ? "" : " ".repeat(Math.round(p.indent / (base.size || 11) * 2))) + p.runs.map((r) => r.s).join("")).join("\n"),
      // the original column width, so lines wrap at the same words as in the PDF
      html: `<div style="width:${Math.ceil(width + 2)}pt;max-width:100%;font-family:${cssFamily(base.family)};font-size:${base.size}pt;` +
            `color:${base.color};line-height:1.15">${html}</div>`,
    };
  }

  const round1 = (v) => Math.round(v * 10) / 10;
  const styleOf = (it) => ({ family: it.family, size: Math.round(it.size * 2) / 2, color: it.color, bold: it.bold, italic: it.italic });
  const sameStyle = (a, b) => a.family === b.family && a.size === b.size && a.color === b.color && a.bold === b.bold && a.italic === b.italic;
  function addRun(runs, s, it) { mergeRun(runs, { s, ...styleOf(it) }); }
  function mergeRun(runs, r) {
    const last = runs[runs.length - 1];
    if (last && (sameStyle(last, r) || !r.s.trim())) last.s += r.s; else runs.push({ ...r });
  }
  function mostCommon(pairs) {
    const tally = new Map();
    for (const [k, n] of pairs) tally.set(k, (tally.get(k) || 0) + n);
    return [...tally.entries()].sort((a, b) => b[1] - a[1])[0]?.[0];
  }
  const cssFamily = (f) => `'${f}', ${/Times|Georgia|Cambria|Garamond|Roman|Serif|Book/i.test(f) ? "serif" : /Courier|Mono|Consol/i.test(f) ? "monospace" : "sans-serif"}`;

  // Real font family and style. Font objects (with their PostScript name, thanks to fontExtraProperties in
  // reader.js) are known once the page has rendered.
  const FAMILY_NAMES = { Helvetica: "Arial", TimesNewRoman: "Times New Roman", Times: "Times New Roman",
    CourierNew: "Courier New", Courier: "Courier New", ArialNarrow: "Arial Narrow", SegoeUI: "Segoe UI",
    CalibriLight: "Calibri Light", CambriaMath: "Cambria Math", ComicSansMS: "Comic Sans MS", TrebuchetMS: "Trebuchet MS" };
  function fontInfo(page, id, style) {
    let f = null;
    try { f = page.commonObjs.has(id) ? page.commonObjs.get(id) : null; } catch (e) { /* not loaded */ }
    const ps = ((f && f.name) || "").replace(/^[A-Z]{6}\+/, "");
    let fam = ps.split(/[-,]/)[0].replace(/(PSMT|PS|MT)$/, "");
    if (/^(CM|LM|SF)[A-Z]*\d*$/i.test(fam)) fam = /^(CMMI|CMSY|CMEX)/i.test(fam) ? "Cambria Math" : "Times New Roman";   // TeX fonts
    fam = FAMILY_NAMES[fam] || fam.replace(/([a-z])([A-Z])/g, "$1 $2");
    if (!fam) fam = style && /serif/.test(style.fontFamily) && !/sans/.test(style.fontFamily) ? "Times New Roman" : "Arial";
    const suffix = ps.slice(ps.split(/[-,]/)[0].length);
    return {
      family: fam,
      bold: !!(f && (f.bold || f.black)) || /bold|black|heavy|semibold|demi/i.test(suffix),
      italic: !!(f && f.italic) || /italic|oblique/i.test(suffix),
    };
  }

  // Colour of the glyphs inside a PDF-space rectangle of the rendered box: the background is the most common
  // colour there, the text colour is the average of the pixels furthest from it.
  function glyphColor(ctx, { box1, scale, v1, canvas }, px1, py1, px2, py2) {
    const [ax, ay] = v1.convertToViewportPoint(px1, py1), [bx, by] = v1.convertToViewportPoint(px2, py2);
    const sx = Math.max(0, Math.floor((Math.min(ax, bx) - box1.x) * scale)), sy = Math.max(0, Math.floor((Math.min(ay, by) - box1.y) * scale));
    const sw = Math.min(canvas.width - sx, Math.ceil(Math.abs(bx - ax) * scale)), sh = Math.min(canvas.height - sy, Math.ceil(Math.abs(by - ay) * scale));
    if (sw < 1 || sh < 1) return "#000000";
    const px = ctx.getImageData(sx, sy, sw, sh).data;
    const tally = new Map();
    for (let i = 0; i < px.length; i += 4) {
      const k = ((px[i] >> 4) << 8) | ((px[i + 1] >> 4) << 4) | (px[i + 2] >> 4);
      tally.set(k, (tally.get(k) || 0) + 1);
    }
    const bgKey = [...tally.entries()].sort((a, b) => b[1] - a[1])[0][0];
    const bg = [((bgKey >> 8) & 15) * 16 + 8, ((bgKey >> 4) & 15) * 16 + 8, (bgKey & 15) * 16 + 8];
    let maxD = 0;
    const dist = [];
    for (let i = 0; i < px.length; i += 4) {
      const dd = Math.abs(px[i] - bg[0]) + Math.abs(px[i + 1] - bg[1]) + Math.abs(px[i + 2] - bg[2]);
      dist.push(dd);
      if (dd > maxD) maxD = dd;
    }
    if (maxD < 60) return "#000000";
    let r = 0, g = 0, b = 0, n = 0;
    for (let j = 0; j < dist.length; j++) {
      if (dist[j] < maxD * 0.75) continue;
      r += px[j * 4]; g += px[j * 4 + 1]; b += px[j * 4 + 2]; n++;
    }
    const hex = (v) => Math.round(v / n).toString(16).padStart(2, "0");
    const col = `#${hex(r)}${hex(g)}${hex(b)}`;
    return /^#[0-3][0-9a-f][0-3][0-9a-f][0-3][0-9a-f]$/.test(col) ? "#000000" : col;   // near-black antialiasing -> black
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
