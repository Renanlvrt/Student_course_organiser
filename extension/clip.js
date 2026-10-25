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

  // Hosts live in the browser's top layer (Popover API): above every page layer and stacking context, so the
  // page can't react to the drag (Overleaf's draggable tabs, editors that grab the mouse...).
  function makeHost(small) {
    const host = document.createElement("alto-clip");
    host.setAttribute("popover", "manual");
    host.style.cssText = small
      ? "position:fixed;inset:auto 0 0 auto;width:auto;height:auto;margin:0;padding:0;border:0;background:transparent;overflow:visible"
      : "position:fixed;inset:0;width:100vw;height:100vh;max-width:none;max-height:none;margin:0;padding:0;border:0;" +
        "background:transparent;overflow:visible;z-index:2147483647";
    const root = host.attachShadow({ mode: "closed" });
    const sheet = new CSSStyleSheet();             // constructable sheets are not blocked by page CSPs
    sheet.replaceSync(CSS);
    root.adoptedStyleSheets = [sheet];
    document.documentElement.appendChild(host);
    try { host.showPopover(); } catch (e) { host.style.zIndex = "2147483647"; }   // no Popover API: highest z-index
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
    const { host, root } = makeHost(true);
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
    // PDF viewers inside the page (Overleaf's preview, other PDF.js viewers): their text layer is positioned text,
    // laid out with the same engine as the built-in reader instead of the HTML walker.
    const pdfLayers = mode === "text" ? boxes.map((b) => pdfTextItems(client(b.page), sx, sy)) : [];
    const embeddedPdf = pdfLayers.length && pdfLayers.every((items) => items && items.length);
    const plan = mode === "text" && !embeddedPdf ? extract(boxes.map((b) => client(b.page))) : null;
    const toPage = (r) => DOMRect.fromRect({ x: r.left + sx, y: r.top + sy, width: r.width, height: r.height });
    if (plan) for (const v of plan.visuals) v.page = toPage(v.rect);

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
      if (embeddedPdf) {
        const parts = [];
        for (let k = 0; k < boxes.length; k++) {
          const b = boxes[k].page, s = await shotFor(b);
          const bmp = await createImageBitmap(pieces[k]);
          const canvas = new OffscreenCanvas(bmp.width, bmp.height);
          canvas.getContext("2d", { willReadFrequently: true }).drawImage(bmp, 0, 0);
          // page CSS pixels with y growing upwards, like PDF space; the raster is the screenshot of the box
          const v1 = { convertToViewportPoint: (x, y) => [x, -y], convertToPdfPoint: (x, y) => [x, -y] };
          const raster = { canvas, box1: { x: b.left, y: b.top }, scale: s.ratio, v1 };
          parts.push(await layoutItems(pdfLayers[k], [b.left, -b.bottom, b.right, -b.top], raster, 0.75));
        }
        html = parts.map((x) => x.html).join("");
        text = parts.map((x) => x.text).filter(Boolean).join("\n\n");
        summary = "Copied text from the PDF · Ctrl+V";
      } else if (plan) {
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

  // Text items of a PDF.js text layer inside `sel` (client coords), in page CSS pixels with y growing upwards.
  // Null when the box isn't over such a layer.
  function pdfTextItems(sel, sx, sy) {
    const layer = [...document.querySelectorAll(".textLayer")].find((l) => {
      const a = intersect(l.getBoundingClientRect(), sel);
      return a && a.width * a.height > sel.width * sel.height * 0.5;
    });
    if (!layer) return null;
    const items = [];
    for (const span of layer.querySelectorAll("span")) {
      if (span.children.length || !span.textContent.trim()) continue;
      const r = span.getBoundingClientRect();
      if (!r.width || !r.height || !centreIn(r, sel)) continue;
      const cs = getComputedStyle(span);
      const size = parseFloat(cs.fontSize) || r.height;
      const fam = /mono/i.test(cs.fontFamily) ? "Courier New" : /serif/i.test(cs.fontFamily) && !/sans/i.test(cs.fontFamily) ? "Times New Roman" : "Arial";
      const a = span.closest("a");
      items.push({ str: span.textContent, x: r.left + sx, y: -(r.top + sy + size * 0.8), w: r.width, size, family: fam,
                   bold: false, italic: false, mathFont: false, href: a ? a.href : null, color: null });
    }
    return items;
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
    "SELECT", "TEXTAREA", "METER", "PROGRESS", "AUDIO"]);
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
    // Side-by-side boxes (flex/grid rows: menus, buttons, cards, key/value grids) become tables so they keep their
    // layout and stay editable. Text is never turned into a picture in this mode, whatever is behind it.
    const sideBySide = (node, cs, r) => {
      if (!/^(inline-)?(flex|grid)$/.test(cs.display) || !clipArea(r) || !node.textContent.trim()) return false;
      const kids = [...node.children].map((k) => k.getBoundingClientRect()).filter((k) => k.width > 0 && k.height > 0 && hit(k));
      for (let i = 1; i < kids.length; i++) {
        const p = kids[i - 1], k = kids[i];
        if (k.left >= p.right - 2 && k.top < p.bottom && k.bottom > p.top) return true;
      }
      return false;
    };
    const visuals = [];
    const lines = [];
    let line = "";
    const flush = () => { if (line.trim()) lines.push(line.replace(/ +/g, " ").trim()); line = ""; };
    const out = document.createElement("div");
    const base = getComputedStyle(document.body);
    // the box's own width, so lines wrap where they did on screen
    out.setAttribute("style", `width:${Math.round(Math.max(...sels.map((s) => s.width)))}px;max-width:100%;` +
                              `font-family:${base.fontFamily};font-size:${base.fontSize};color:${readableColor(base.color)};line-height:${base.lineHeight}`);

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
          if (sideBySide(child, cs, r)) { rowTable(child, into, cs); continue; }
          if (VISUAL.has(tag) || child.matches(VISUAL_SEL) || iconLike(child, cs, r)) {
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
            continue;
          }
        }
        const tag = child.tagName.toUpperCase();
        const block = isBlock(cs) && cs.display !== "table-cell";
        // headings become paragraphs stating their exact look: OneNote and Word would apply their own heading styles
        const heading = /^H[1-6]$/.test(tag);
        const hasBlocks = [...child.children].some((k) => !/^inline/.test(getComputedStyle(k).display));
        const outTag = heading ? (hasBlocks ? "DIV" : "P") : KEEP.has(tag) && tag !== "BLOCKQUOTE" ? tag : (block ? "DIV" : "SPAN");   // a <p> can't hold blocks
        const copy = document.createElement(outTag);
        if (tag === "A" && child.href) copy.setAttribute("href", child.href);
        for (const a of ["colspan", "rowspan", "start"]) if (child.hasAttribute(a)) copy.setAttribute(a, child.getAttribute(a));
        if (tag === "TABLE") {                     // OneNote takes borders from the attribute, not CSS
          const cell = child.querySelector("td, th");
          const ruled = parseFloat(cs.borderTopWidth) > 0 || (cell && parseFloat(getComputedStyle(cell).borderTopWidth) > 0);
          copy.setAttribute("border", ruled ? "1" : "0");
          copy.setAttribute("cellspacing", "0");
        }
        if (tag === "TD" || tag === "TH") copy.setAttribute("width", Math.round(child.getBoundingClientRect().width));
        const style = heading ? cellFont(cs, true) : styleDiff(cs, parentCs, block, tag);
        if (style) copy.setAttribute("style", style);
        if (tag === "BR") { into.appendChild(copy); flush(); continue; }
        // paragraph-level blocks (and whole tables/lists) carry their own indent and the gap above them
        const leaf = block && !cellDepth && !/^(LI|TD|TH|TR|TBODY|THEAD|TFOOT)$/.test(tag) && !child.closest("li, td, th") &&
                     (/^(TABLE|UL|OL|DL)$/.test(tag) ||
                      ![...child.children].some((k) => { const d = getComputedStyle(k).display; return !/^inline/.test(d) && d !== "none" && d !== "contents"; }));
        const spacerAt = leaf ? into.childNodes.length : -1;
        if (/^(TABLE|UL|OL|DL)$/.test(tag)) cellDepth++;
        walk(child, copy, cs);
        if (/^(TABLE|UL|OL|DL)$/.test(tag)) cellDepth--;
        if (copy.childNodes.length || tag === "HR") {
          into.appendChild(copy);
          if (leaf) blockDone(child, cs, copy, into, spacerAt, /^(TABLE|UL|OL|DL)$/.test(tag));
        }
        if (block) flush();
        if (tag === "TD" || tag === "TH") line += "\t";
      }
    };

    // Side-by-side boxes (flex/grid rows) -> a borderless table, one row per visual row, so they stay editable.
    const rowTable = (node, into, cs) => {
      const rows = [];
      for (const k of node.children) {
        const kc = getComputedStyle(k);
        if (kc.display === "none" || kc.visibility === "hidden") continue;
        const kr = k.getBoundingClientRect();
        if (!kr.width || !kr.height || !hit(kr)) continue;
        let row = rows.find((rw) => kr.top < rw.bottom - 2 && kr.bottom > rw.top + 2);
        if (!row) { row = { top: kr.top, bottom: kr.bottom, cells: [] }; rows.push(row); }
        row.cells.push({ k, kr });
        row.bottom = Math.max(row.bottom, kr.bottom);
      }
      flush();
      const table = document.createElement("table");
      table.setAttribute("border", "0");
      table.setAttribute("cellspacing", "0");
      for (const row of rows.sort((a, b) => a.top - b.top)) {
        const tr = table.insertRow();
        row.cells.sort((a, b) => a.kr.left - b.kr.left).forEach(({ k, kr }, n) => {
          const td = tr.insertCell();
          td.setAttribute("width", Math.round(kr.width));
          td.setAttribute("style", cellFont(getComputedStyle(k)) + ";vertical-align:top");
          cellDepth++;
          walk(k.tagName === "LI" ? k : { childNodes: [k] }, td, cs);   // a list item's content, without a stray bullet
          cellDepth--;
          if (!td.textContent.trim() && !td.querySelector("img")) td.remove();   // nothing visible in this box
          else if (n < row.cells.length - 1) line += "\t";
        });
        if (!tr.cells.length) tr.remove();
        flush();
      }
      if (table.rows.length) {
        const at = into.childNodes.length;
        into.appendChild(table);
        if (!cellDepth) blockDone(node, cs, table, into, at, true);   // nested rows sit in their cell, no page offset
      }
    };
    // Layout in the form OneNote keeps: each paragraph-level block gets its indent (and centring) as its own
    // margin-left - OneNote ignores text-align:center and container margins - and vertical gaps become sized
    // empty paragraphs, collapsed like CSS margins (the larger of the two wins).
    let cellDepth = 0, pendingGap = 0, blocksSeen = 0;
    const boxLeft = Math.min(...sels.map((s) => s.left));
    const placed = [];                             // {el: output element, left, right} - indents fixed up at the end
    const blockDone = (src, cs, el, into, at, whole) => {
      const gap = Math.max(pendingGap, parseFloat(cs.marginTop) || 0);
      if (blocksSeen++ && spacerHtml(gap)) {
        const tmp = document.createElement("div");
        tmp.innerHTML = spacerHtml(gap);
        into.insertBefore(tmp.firstChild, into.childNodes[at] || null);
      }
      pendingGap = parseFloat(cs.marginBottom) || 0;
      const r = src.getBoundingClientRect();
      let left = Math.max(boxLeft, r.left + (whole ? 0 : parseFloat(cs.paddingLeft) + parseFloat(cs.borderLeftWidth)));
      let right = 0;
      if (!whole && cs.textAlign === "center") {   // centre by indenting to the middle (OneNote drops text-align:center)
        const range = document.createRange();
        range.selectNodeContents(src);
        const inner = r.width - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
        right = Math.max(0, (inner - range.getBoundingClientRect().width) / 2);
        left += right;
      }
      placed.push({ el, left, right });
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
    // indents relative to the leftmost block, as margins on each block (OneNote turns them into indent levels)
    const minLeft = Math.min(...placed.map((p) => p.left));
    for (const p of placed) {
      const margin = `margin:0 ${Math.round(p.right * 0.75)}pt 0 ${Math.round((p.left - minLeft) * 0.75)}pt`;   // the 4-value form OneNote reads
      p.el.setAttribute("style", [p.el.getAttribute("style"), margin].filter(Boolean).join(";"));
    }
    return { root: out, visuals, text: lines.join("\n") };
  }

  function styleDiff(cs, parentCs, block, tag) {
    const parts = [];
    for (const p of STYLE_PROPS) {
      const v = p === "color" ? readableColor(cs.color) : cs.getPropertyValue(p);
      const pv = p === "color" ? readableColor(parentCs.color) : parentCs.getPropertyValue(p);
      if (v !== pv && !(p === "vertical-align" && v === "baseline") &&
          !(p === "white-space" && !/^pre/.test(v))) parts.push(`${p}:${v}`);
    }
    const bg = cs.backgroundColor;
    if ((!block || tag === "TD" || tag === "TH") && bg && bg !== "rgba(0, 0, 0, 0)" && bg !== "transparent" &&
        bg !== parentCs.backgroundColor) parts.push(`background-color:${bg}`);
    if (block) {
      if (cs.textAlign !== parentCs.textAlign && !/^(start|left)$/.test(cs.textAlign)) parts.push(`text-align:${cs.textAlign}`);
      if (tag === "BLOCKQUOTE" || parseFloat(cs.borderLeftWidth) >= 2) {
        if (parseFloat(cs.borderLeftWidth) > 0) parts.push(`border-left:${cs.borderLeftWidth} solid ${cs.borderLeftColor}`);
        parts.push(`padding-left:${cs.paddingLeft}`);
      }
    }
    if (tag === "TD" || tag === "TH") parts.push(cellFont(cs), "vertical-align:top");
    if (tag === "TABLE") parts.push("border-collapse:collapse");
    return parts.join(";");
  }

  // Relative luminance (0 black .. 1 white) of a CSS colour like rgb(r, g, b) or #rrggbb.
  // Colours for a white page: light text from dark themes / text over pictures becomes its dark equivalent
  // (grey and white -> black; coloured text such as links keeps its hue, darker).
  function readableColor(css) {
    const m = String(css).match(/\d+(\.\d+)?/g);
    if (!m || luminance(css) <= 0.6) return css;
    const [r, g, b] = m.slice(0, 3).map(Number);
    if (Math.max(r, g, b) - Math.min(r, g, b) < 40) return "rgb(0, 0, 0)";
    const k = 0.3 / luminance(css);
    return `rgb(${Math.round(r * k)}, ${Math.round(g * k)}, ${Math.round(b * k)})`;
  }
  function luminance(css) {
    const m = String(css).match(/\d+(\.\d+)?/g);
    let [r, g, b] = css.startsWith("#") ? [1, 3, 5].map((k) => parseInt(css.slice(k, k + 2), 16)) : (m || [0, 0, 0]).map(Number);
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
  }
  // Vertical space as an empty paragraph of the right size (OneNote drops paragraph margins).
  const spacerHtml = (px) => (px * 0.75 >= 3 ? `<p style="margin:0;font-size:${Math.max(1, Math.round(px * 0.75 / 1.15))}pt">&nbsp;</p>` : "");
  // OneNote resets the font inside table cells, so cells state theirs in full.
  const cellFont = (cs, explicit) => `font-family:${cs.fontFamily};font-size:${cs.fontSize};color:${readableColor(cs.color)}` +
    (parseInt(cs.fontWeight, 10) >= 600 ? ";font-weight:bold" : explicit ? ";font-weight:normal" : "") +
    (cs.fontStyle === "italic" ? ";font-style:italic" : "");
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
  async function pdfRich(page, rect, raster) {
    const [x1, y1, x2, y2] = rect;
    const content = await page.getTextContent();
    const links = (await page.getAnnotations()).filter((a) => a.subtype === "Link" && (a.url || a.unsafeUrl))
      .map((a) => ({ r: a.rect, url: a.url || a.unsafeUrl }));
    const ctx = raster.canvas.getContext("2d", { willReadFrequently: true });
    const items = [];
    for (const it of content.items) {
      if (!it.str || !it.str.trim() || !it.transform) continue;   // PDF.js fills gaps with wide space items; spacing comes from positions
      const [a, b, c, d, x, y] = it.transform;
      const size = Math.hypot(c, d) || it.height || 10;
      const w = it.width || 0;
      const cx = x + w / 2, cy = y + size * 0.35;
      if (cx < x1 || cx > x2 || cy < y1 || cy > y2 || Math.abs(b) > Math.abs(a) * 0.1) continue;   // skip rotated text
      const font = fontInfo(page, it.fontName, content.styles[it.fontName]);
      const link = links.find((l) => cx >= l.r[0] && cx <= l.r[2] && cy >= l.r[1] && cy <= l.r[3]);
      items.push({ str: it.str, x, y, w, size, ...font, href: link ? link.url : null,
                   color: glyphColor(ctx, raster, x, y - size * 0.2, x + w, y + size * 0.8) });
    }
    return layoutItems(items, rect, raster, 1);
  }

  // The layout engine shared by the PDF reader and PDF viewers embedded in web pages (Overleaf...): text items
  // (x, baseline y growing upwards, width, size, font, colour, link) -> formatted HTML in OneNote's subset.
  // `ptPer` converts the items' units to points (1 for PDF points, 0.75 for CSS pixels).
  async function layoutItems(items, [x1, y1, x2, y2], raster, ptPer) {
    if (!items.length) return { text: "", html: "" };
    const ctx = raster.canvas.getContext("2d", { willReadFrequently: true });
    for (const it of items) {                      // colour from the glyph pixels when the source didn't say
      if (!it.color) it.color = readableColor(glyphColor(ctx, raster, it.x, it.y - it.size * 0.2, it.x + it.w, it.y + it.size * 0.8));
    }

    // Ruled tables: the grid comes from the ruling lines drawn on the page (like PyMuPDF's find_tables), so text
    // wrapped inside a cell stays in its cell instead of becoming extra rows.
    const gridTables = rasterGrids(ctx, raster).map((g) => {
      const cells = g.rows.slice(1).map(() => g.cols.slice(1).map(() => []));
      for (const it of items) {
        const cx = it.x + it.w / 2, cy = it.y + it.size * 0.35;
        const r = g.rows.findIndex((y, k) => k < g.rows.length - 1 && cy <= y && cy >= g.rows[k + 1]);
        const c = g.cols.findIndex((x, k) => k < g.cols.length - 1 && cx >= x && cx <= g.cols[k + 1]);
        if (r < 0 || c < 0) continue;
        cells[r][c].push(it);
        it.inGrid = true;
      }
      const rows = cells.map((row, k) => ({ line: { y: g.rows[k], size: 0 }, cells: row.map(cellRuns) }))
        .filter((row) => row.cells.some((c) => c.length));
      return { kind: "table", ruled: true, rows, anchors: g.cols.slice(0, -1), right: g.cols[g.cols.length - 1],
               top: g.rows[0], bottomLine: { y: g.rows[g.rows.length - 1], size: 0 } };
    }).filter((t) => t.rows.length);
    items = items.filter((it) => !it.inGrid);

    // lines: same baseline, left to right; raised/lowered small text (indices, exponents) stays on its line
    items.sort((p, q) => (Math.abs(q.y - p.y) > Math.max(p.size, q.size) * 0.45 ? q.y - p.y : p.x - q.x));
    const lines = [];
    for (const it of items) {
      const last = lines[lines.length - 1];
      if (last && Math.abs(last.y - it.y) <= Math.max(last.first, it.size) * 0.45 && it.x >= last.x - it.size) {
        last.items.push(it);
        last.end = Math.max(last.end, it.x + it.w);
      } else {
        lines.push({ y: it.y, x: it.x, end: it.x + it.w, first: it.size, items: [it] });
      }
    }
    for (const l of lines) {
      l.items.sort((p, q) => p.x - q.x);
      l.runs = runsOf(l.items);
      l.text = l.runs.map((r) => r.s).join("");
      l.size = mostCommon(l.runs.filter((r) => r.s.trim() && !r.va).map((r) => [r.size, r.s.length])) || l.first;
      l.y = mostCommon(l.items.filter((it) => Math.abs(it.size - l.size) < 0.6).map((it) => [it.y, it.str.length])) ?? l.y;
      l.math = isMathLine(l);
      // segments: pieces of the line separated by a wide gap (table cells, tab stops)
      l.segs = [];
      for (const it of l.items) {
        const s = l.segs[l.segs.length - 1];
        if (s && it.x - s.end < Math.max(l.size * 1.2, 6)) { s.items.push(it); s.end = Math.max(s.end, it.x + it.w); }
        else l.segs.push({ x: it.x, end: it.x + it.w, items: [it] });
      }
    }

    // A display equation is one picture: short lines next to an equation line ("otherwise", "(1)", a fraction's
    // denominator) belong to it.
    const colW = Math.max(1, Math.max(...lines.map((l) => l.end)) - Math.min(...lines.map((l) => l.x)));
    for (let pass = 0; pass < 3; pass++) {
      lines.forEach((l, k) => {
        if (l.math || l.end - l.x > colW * 0.6) return;
        const near = (o) => o && o.math && Math.abs(o.y - l.y) < Math.max(o.size, l.size) * 2.2;
        if (near(lines[k - 1]) || near(lines[k + 1])) l.math = true;
      });
    }
    const left = Math.min(...lines.map((l) => l.x), ...gridTables.map((t) => t.anchors[0]));
    const right = Math.max(...lines.map((l) => l.end), ...gridTables.map((t) => t.right));
    const width = Math.max(1, right - left);
    const centred = (l) => {
      const lm = l.x - x1, rm = x2 - l.end;
      return l.end - l.x < width * 0.85 && lm > l.size && Math.abs(lm - rm) < Math.max(l.size * 1.5, (x2 - x1) * 0.06);
    };

    // tables: two or more consecutive lines whose segments start at the same column positions
    const blocks = [];
    for (let i = 0; i < lines.length; i++) {
      const l = lines[i];
      const b = blocks[blocks.length - 1];
      if (l.math) {                                  // equations: pasted as they are typeset (see mathImage)
        if (b && b.kind === "math" && b.lines[b.lines.length - 1].y - l.y < Math.max(l.size, b.lines[0].size) * 2.2) b.lines.push(l);
        else blocks.push({ kind: "math", lines: [l] });
        continue;
      }
      const t = tableAt(lines, i);
      if (t) { blocks.push(t); i = t.last; continue; }
      const prev = b && b.kind === "para" && b.lines[b.lines.length - 1];
      const joins = prev &&
        prev.y - l.y < Math.max(prev.size, l.size) * 1.45 &&            // normal line spacing
        Math.abs(prev.size - l.size) < 1 &&                            // same size
        prev.end > right - Math.max(prev.size * 3, width * 0.12) &&   // previous line ran to the right edge
        Math.abs(l.x - b.lines[0].x) < prev.size * 2.5 &&              // same left edge (or first-line indent)
        centred(prev) === centred(l);
      if (joins) {
        const lastRun = b.runs[b.runs.length - 1];
        if (/[A-Za-z]-$/.test(lastRun.s) && /^[a-z]/.test(l.text)) lastRun.s = lastRun.s.slice(0, -1);   // re-join hyphenated words
        else if (!/\s$/.test(lastRun.s)) b.runs.push({ ...lastRun, s: " ", href: null, va: null });
        for (const r of l.runs) mergeRun(b.runs, r);
        b.lines.push(l);
      } else {
        blocks.push({ kind: "para", lines: [l], runs: l.runs.map((r) => ({ ...r })), indent: l.x - left, centred: centred(l) });
      }
    }
    blocks.push(...gridTables);                                     // in reading order, top first (y grows upwards)
    const topOf = (b) => (b.kind === "para" || b.kind === "math" ? b.lines[0].y + b.lines[0].size : b.top ?? b.rows[0].line.y + b.rows[0].line.size);
    blocks.sort((a, b) => topOf(b) - topOf(a));
    for (let i = 0; i + 1 < blocks.length; i++) {                     // space below each block, from the baselines
      const a = blocks[i], b = blocks[i + 1];
      const lastA = a.lines ? a.lines[a.lines.length - 1] : a.bottomLine || a.rows[a.rows.length - 1].line;
      const firstB = b.lines ? b.lines[0] : b.rows[0].line;
      a.after = Math.max(0, lastA.y - firstB.y - firstB.size * 1.25);
    }
    for (const b of blocks) if (b.kind === "table" && b.ruled === undefined) b.ruled = isRuled(ctx, raster, b);
    for (const b of blocks) if (b.kind === "math") b.img = await mathImage(b, raster, ptPer);

    // HTML in the subset OneNote keeps (checked by pasting into OneNote): fonts, sizes, colours, bold/italic,
    // links, sub/superscripts, margin-left indents and tables. It drops centring, margins and line spacing, so
    // centred lines are indented to the middle (margin-right too, which centres them in Word) and gaps become
    // sized empty paragraphs.
    const pt = (v) => round1(v * ptPer);
    const all = blocks.flatMap((b) => (b.kind === "para" ? b.runs : b.kind === "table" ? b.rows.flatMap((r) => r.cells.flat()) : []));
    const common = (key) => mostCommon(all.filter((r) => r.s.trim()).map((r) => [r[key], r.s.length]));
    const base = { family: common("family") || "Arial", size: common("size") || 11, color: common("color") || "#000000" };
    const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    const span = (r, full) => {
      const s = [];
      if (full || r.family !== base.family) s.push(`font-family:${cssFamily(r.family)}`);
      if (full || r.size !== base.size) s.push(`font-size:${Math.round(r.size * ptPer * 2) / 2}pt`);
      if (full || r.color !== base.color) s.push(`color:${r.color}`);
      if (r.bold) s.push("font-weight:bold");
      if (r.italic) s.push("font-style:italic");
      let h = s.length ? `<span style="${s.join(";")}">${esc(r.s)}</span>` : esc(r.s);
      if (r.va) h = `<${r.va}>${h}</${r.va}>`;              // exponents and indices
      if (r.href) h = `<a href="${esc(r.href)}">${h}</a>`;  // links stay clickable
      return h;
    };
    const spacer = (gap) => (gap * ptPer >= 2.5 ? `<p style="margin:0;font-size:${Math.max(1, Math.round(gap * ptPer / 1.15))}pt">&nbsp;</p>` : "");
    const html = blocks.map((b) => {
      if (b.kind === "math") {
        const indent = b.centred ? 0 : pt(b.left - left);
        return (b.img ? `<p style="margin:0 0pt 0 ${indent}pt">${b.img}</p>` : "") + spacer(b.after);
      }
      if (b.kind === "table") {
        const colW = b.anchors.map((x, k) => ((b.anchors[k + 1] ?? b.right) - x) * ptPer * 4 / 3);   // pt -> px
        const rows = b.rows.map((r) => "<tr>" + r.cells.map((cell, k) =>
          `<td width="${Math.round(colW[k])}" style="width:${Math.round(colW[k])}px;vertical-align:top;padding:1pt 4pt">` +
          `${cell.map((x) => span(x, true)).join("") || "&nbsp;"}</td>`).join("") + "</tr>").join("");
        return `<table border="${b.ruled ? 1 : 0}" cellspacing="0" style="border-collapse:collapse;margin:0">${rows}</table>` + spacer(b.after);
      }
      const lineW = Math.max(...b.lines.map((l) => l.end - l.x));
      const pad = b.centred ? Math.max(0, (x2 - x1 - lineW) / 2 - (left - x1)) : b.indent;
      const style = [`margin:0 ${b.centred ? pt(pad) : 0}pt 0 ${pt(pad)}pt`];
      if (b.centred) style.push("text-align:center");
      return `<p style="${style.join(";")}">${b.runs.map((r) => span(r)).join("")}</p>` + spacer(b.after);
    }).join("");
    const text = blocks.map((b) => (b.kind === "table"
      ? b.rows.map((r) => r.cells.map((c) => c.map((x) => x.s).join("")).join("\t")).join("\n")
      : b.kind === "math" ? b.lines.map((l) => l.text).join("\n")
      : (b.centred ? "" : " ".repeat(Math.round(b.indent / (base.size || 11) * 2))) + b.runs.map((r) => r.s).join(""))).join("\n");
    return {
      text,
      // the original column width (Word), so lines wrap at the same words as in the PDF
      html: `<div style="width:${Math.ceil(width * ptPer + 2)}pt;max-width:100%;font-family:${cssFamily(base.family)};` +
            `font-size:${Math.round(base.size * ptPer * 2) / 2}pt;color:${base.color};line-height:1.15">${html}</div>`,
    };
  }

  // Equations: math fonts (TeX's CMMI/CMSY/CMEX, Cambria Math, Symbol...) or mostly mathematical symbols. Their
  // text would read like "s = Σ x i 2"; pasted as the typeset picture they look exactly like the paper.
  const MATH_CHARS = /[Ͱ-Ͽ←-⇿∀-⋿⌀-⏿⟀-⟯⦀-⧿⨀-⫿\u{1d400}-\u{1d7ff}∑∏∫√∞±×÷≤≥≠≈∂∇=+^_|]/u;
  function isMathLine(l) {
    const chars = l.items.reduce((n, it) => n + it.str.replace(/\s/g, "").length, 0) || 1;
    const fromMathFonts = l.items.filter((it) => it.mathFont).reduce((n, it) => n + it.str.replace(/\s/g, "").length, 0) / chars;
    const symbols = [...l.text.replace(/\s/g, "")].filter((ch) => MATH_CHARS.test(ch)).length / chars;
    const words = (l.text.match(/[A-Za-z]{3,}/g) || []).length;
    const scattered = l.items.length >= 4 && chars / l.items.length < 2.2;
    const operators = /[=+−<>≤≥∑∫√∂]/.test(l.text);   // = + − < > ≤ ≥ ∑ ∫ √ ∂
    return (fromMathFonts > 0.35 && words < 6) || symbols > 0.3 || (scattered && symbols > 0.12 && words < 4) ||
           (scattered && operators && words < 8 && chars / l.items.length < 3);   // text layers: no font names, many tiny pieces
  }

  async function mathImage(b, { canvas, box1, scale, v1 }, ptPer) {
    const its = b.lines.flatMap((l) => l.items);
    const xa = Math.min(...its.map((it) => it.x)) - 2, xb = Math.max(...its.map((it) => it.x + it.w)) + 2;
    const ya = Math.min(...its.map((it) => it.y - it.size * 0.45)) - 2, yb = Math.max(...its.map((it) => it.y + it.size * 1.05)) + 2;
    b.left = xa;
    const [ax, ay] = v1.convertToViewportPoint(xa, yb), [bx, by] = v1.convertToViewportPoint(xb, ya);
    const sx = Math.max(0, Math.floor((Math.min(ax, bx) - box1.x) * scale)), sy = Math.max(0, Math.floor((Math.min(ay, by) - box1.y) * scale));
    const sw = Math.min(canvas.width - sx, Math.ceil(Math.abs(bx - ax) * scale)), sh = Math.min(canvas.height - sy, Math.ceil(Math.abs(by - ay) * scale));
    if (sw < 2 || sh < 2) return "";
    const c = new OffscreenCanvas(sw, sh);
    c.getContext("2d").drawImage(canvas, sx, sy, sw, sh, 0, 0, sw, sh);
    const uri = await blobToDataUri(await c.convertToBlob({ type: "image/png" }));
    const w = Math.round((xb - xa) * ptPer * 4 / 3), h = Math.round((yb - ya) * ptPer * 4 / 3);
    const alt = b.lines.map((l) => l.text).join(" ").replace(/"/g, "&quot;");
    return `<img src="${uri}" width="${w}" height="${h}" alt="${alt}">`;
  }

  // Runs of one table cell: its lines top to bottom, joined with spaces (the text reflows in the pasted cell).
  function cellRuns(items) {
    items.sort((p, q) => (Math.abs(q.y - p.y) > Math.min(p.size, q.size) * 0.35 ? q.y - p.y : p.x - q.x));
    const runs = [];
    let line = [];
    const flushLine = () => {
      if (!line.length) return;
      if (runs.length && !/\s$/.test(runs[runs.length - 1].s)) mergeRun(runs, { ...runs[runs.length - 1], s: " " });
      for (const r of runsOf(line)) mergeRun(runs, r);
      line = [];
    };
    for (const it of items) {
      if (line.length && Math.abs(line[0].y - it.y) > Math.min(line[0].size, it.size) * 0.35) flushLine();
      line.push(it);
    }
    flushLine();
    return runs;
  }

  // Ruling-line grids in the rendered box: long dark horizontal and vertical runs, grouped into tables where they
  // cross. Returns row boundaries (PDF y, top first) and column boundaries (PDF x, left first) per table.
  function rasterGrids(ctx, { canvas, box1, scale, v1 }) {
    const W = canvas.width, H = canvas.height;
    if (W < 20 || H < 20) return [];
    const px = ctx.getImageData(0, 0, W, H).data;
    const dark = (x, y) => { const i = (y * W + x) * 4; return px[i] + px[i + 1] + px[i + 2] < 600; };   // light grey rules too
    const minH = Math.max(40, 18 * scale), minV = Math.max(16, 14 * scale);   // longer than any glyph stroke
    const hs = [], vs = [];
    for (let y = 0; y < H; y++) {
      let run = 0;
      for (let x = 0; x <= W; x++) {
        if (x < W && dark(x, y)) { run++; continue; }
        if (run >= minH) hs.push({ y, x0: x - run, x1: x - 1 });
        run = 0;
      }
    }
    for (let x = 0; x < W; x++) {
      let run = 0;
      for (let y = 0; y <= H; y++) {
        if (y < H && dark(x, y)) { run++; continue; }
        if (run >= minV) vs.push({ x, y0: y - run, y1: y - 1 });
        run = 0;
      }
    }
    // merge the pixel rows/columns of one thick line
    const mergeH = [], mergeV = [];
    for (const h of hs) {
      const m = mergeH.find((o) => h.y - o.y1 <= 1 && h.x0 < o.x1 && h.x1 > o.x0);
      if (m) { m.y1 = h.y; m.x0 = Math.min(m.x0, h.x0); m.x1 = Math.max(m.x1, h.x1); } else mergeH.push({ y0: h.y, y1: h.y, x0: h.x0, x1: h.x1 });
    }
    for (const v of vs) {
      const m = mergeV.find((o) => v.x - o.x1 <= 1 && v.y0 < o.y1 && v.y1 > o.y0);
      if (m) { m.x1 = v.x; m.y0 = Math.min(m.y0, v.y0); m.y1 = Math.max(m.y1, v.y1); } else mergeV.push({ x0: v.x, x1: v.x, y0: v.y0, y1: v.y1 });
    }
    const hl = mergeH.filter((h) => h.y1 - h.y0 <= 6).map((h) => ({ y: (h.y0 + h.y1) / 2, x0: h.x0, x1: h.x1 }));
    const vl = mergeV.filter((v) => v.x1 - v.x0 <= 6).map((v) => ({ x: (v.x0 + v.x1) / 2, y0: v.y0, y1: v.y1 }));
    // tables = groups of crossing lines (union-find)
    const segs = [...hl.map((h) => ({ h })), ...vl.map((v) => ({ v }))];
    const parent = segs.map((_, i) => i);
    const find = (i) => (parent[i] === i ? i : (parent[i] = find(parent[i])));
    for (let i = 0; i < hl.length; i++) {
      for (let j = 0; j < vl.length; j++) {
        const h = hl[i], v = vl[j];
        if (v.x >= h.x0 - 3 && v.x <= h.x1 + 3 && h.y >= v.y0 - 3 && h.y <= v.y1 + 3) parent[find(i)] = find(hl.length + j);
      }
    }
    const groups = new Map();
    segs.forEach((sg, i) => { const r = find(i); if (!groups.has(r)) groups.set(r, { h: [], v: [] }); groups.get(r)[sg.h ? "h" : "v"].push(sg.h || sg.v); });
    const toPdf = (cx, cy) => v1.convertToPdfPoint(cx / scale + box1.x, cy / scale + box1.y);
    const uniq = (vals, tol) => vals.sort((a, b) => a - b).filter((v, i, a) => i === 0 || v - a[i - 1] > tol);
    const out = [];
    for (const g of groups.values()) {
      if (g.h.length < 2 || g.v.length < 2) continue;
      const ys = uniq(g.h.map((h) => h.y), 3 * scale), xs = uniq(g.v.map((v) => v.x), 3 * scale);
      if (ys.length < 2 || xs.length < 2) continue;
      out.push({ rows: ys.map((y) => toPdf(xs[0], y)[1]), cols: xs.map((x) => toPdf(x, ys[0])[0]) });
    }
    return out;
  }

  function runsOf(items) {
    // the line's main size and baseline: smaller text clearly above / below it is an exponent / index
    const main = mostCommon(items.map((it) => [Math.round(it.size * 2) / 2, it.str.length])) || 10;
    const baseY = mostCommon(items.filter((it) => Math.abs(it.size - main) < 0.6).map((it) => [it.y, it.str.length])) ?? items[0].y;
    const runs = [];
    let end = null;
    for (const it of items) {
      const small = it.size < main * 0.88;
      const va = small && it.y > baseY + main * 0.15 ? "sup" : small && it.y < baseY - main * 0.08 ? "sub" : null;
      if (end !== null && it.x - end > it.size * 0.15 && runs.length && !/\s$/.test(runs[runs.length - 1].s) && !/^\s/.test(it.str)) {
        mergeRun(runs, { s: " ", ...styleOf(it), va: null, href: null });
      }
      mergeRun(runs, { s: it.str, ...styleOf(it), size: va ? main : Math.round(it.size * 2) / 2, va });
      end = it.x + it.w;
    }
    return runs;
  }

  // A table starting at line i: consecutive lines (normal spacing) with 2+ segments whose starts line up.
  function tableAt(lines, i) {
    const rows = [];
    for (let j = i; j < lines.length; j++) {
      const l = lines[j];
      if (l.segs.length < 2) break;
      if (rows.length && lines[j - 1].y - l.y > Math.max(l.size, lines[j - 1].size) * 3) break;
      rows.push(l);
    }
    if (rows.length < 2) return null;
    // column anchors: segment starts seen on at least two rows
    const tol = Math.max(...rows.map((r) => r.size)) * 0.8;
    const starts = rows.flatMap((r) => r.segs.map((s) => s.x)).sort((a, b) => a - b);
    const cols = [];
    for (const x of starts) {
      const c = cols[cols.length - 1];
      if (c && x - c.max <= tol) { c.max = x; c.n++; } else cols.push({ min: x, max: x, n: 1 });
    }
    const anchors = cols.filter((c) => c.n >= 2).map((c) => c.min);
    if (anchors.length < 2) return null;
    const aligned = rows.filter((r) => r.segs.every((s) => anchors.some((a) => Math.abs(s.x - a) <= tol) || s.x > anchors[anchors.length - 1]));
    if (aligned.length < rows.length * 0.75) return null;
    const colOf = (x) => { let k = 0; anchors.forEach((a, n) => { if (x >= a - tol) k = n; }); return k; };
    return {
      kind: "table", last: i + rows.length - 1, anchors,
      right: Math.max(...rows.map((r) => r.end)) + tol,
      rows: rows.map((r) => {
        const cells = anchors.map(() => []);
        for (const s of r.segs) for (const run of runsOf(s.items)) mergeRun(cells[colOf(s.x)], run);
        return { line: r, cells, top: r.y + r.size, bottom: r.y - r.size * 0.3 };
      }),
    };
  }

  // Does the rendered table have ruling lines? Look for a long dark horizontal line between its first two rows.
  function isRuled(ctx, { box1, scale, v1, canvas }, table) {
    if (table.rows.length < 2) return false;
    const [r0, r1] = table.rows;
    const ys = [];
    for (let k = 1; k < 8; k++) ys.push(r0.bottom - (r0.bottom - r1.top) * (k / 8));
    const xa = Math.min(...table.rows.map((r) => r.line.x)), xb = Math.max(...table.rows.map((r) => r.line.end));
    for (const py of ys) {
      const [ax, ay] = v1.convertToViewportPoint(xa, py), [bx] = v1.convertToViewportPoint(xb, py);
      const sx = Math.max(0, Math.floor((Math.min(ax, bx) - box1.x) * scale)), sy = Math.floor((ay - box1.y) * scale);
      const sw = Math.min(canvas.width - sx, Math.ceil(Math.abs(bx - ax) * scale));
      if (sy < 0 || sy >= canvas.height || sw < 10) continue;
      const px = ctx.getImageData(sx, sy, sw, 1).data;
      let dark = 0;
      for (let i = 0; i < px.length; i += 4) if (px[i] + px[i + 1] + px[i + 2] < 600) dark++;
      if (dark > sw * 0.6) return true;
    }
    return false;
  }

  const round1 = (v) => Math.round(v * 10) / 10;
  const styleOf = (it) => ({ family: it.family, size: Math.round(it.size * 2) / 2, color: it.color, bold: it.bold,
                              italic: it.italic, href: it.href || null, va: null });
  const sameStyle = (a, b) => a.family === b.family && a.size === b.size && a.color === b.color && a.bold === b.bold &&
                              a.italic === b.italic && (a.href || null) === (b.href || null) && (a.va || null) === (b.va || null);
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
    const mathFont = /^(CMMI|CMSY|CMEX|CMBSY|MSAM|MSBM|EUFM|EUSM|RSFS|STIX|LMMath|Latin ?Modern ?Math|Cambria ?Math|Symbol|MTExtra|Euclid|TeXGyre\w*Math|XITSMath)/i.test(fam) ||
                     /Math/i.test(fam);
    if (/^(CM|LM|SF)[A-Z]*\d*$/i.test(fam)) fam = /^(CMMI|CMSY|CMEX)/i.test(fam) ? "Cambria Math" : "Times New Roman";   // TeX fonts
    fam = FAMILY_NAMES[fam] || fam.replace(/([a-z])([A-Z])/g, "$1 $2");
    if (!fam) fam = style && /serif/.test(style.fontFamily) && !/sans/.test(style.fontFamily) ? "Times New Roman" : "Arial";
    const suffix = ps.slice(ps.split(/[-,]/)[0].length);
    return {
      family: fam,
      bold: !!(f && (f.bold || f.black)) || /bold|black|heavy|semibold|demi/i.test(suffix),
      italic: !!(f && f.italic) || /italic|oblique/i.test(suffix),
      mathFont,
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
