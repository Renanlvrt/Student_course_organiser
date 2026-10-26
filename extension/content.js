// Runs on Blackboard pages. Uses Blackboard's own REST API with the logged-in session
// (same origin, cookies included) to get the exact course code and folder path.
(() => {
  if (window.__altoHelper) return;
  window.__altoHelper = true;

  const API = location.origin + "/learn/api/public";
  const courseCache = {};

  const clean = (s) => (s || "").replace(/\s+/g, " ").trim().slice(0, 200);

  function courseIdFrom(str) {
    const m = (str || "").match(/courses\/(_\d+_\d+)/) || (str || "").match(/course_id=(_\d+_\d+)/);
    return m ? m[1] : null;
  }

  function currentCourseId() {
    let id = courseIdFrom(location.href);
    if (!id) {
      try { id = courseIdFrom(window.top.location.href); } catch (e) { /* cross-origin frame */ }
    }
    return id;
  }

  async function api(path) {
    const r = await fetch(API + path, { credentials: "include", headers: { Accept: "application/json" } });
    if (!r.ok) throw new Error(`${r.status} ${path}`);
    return r.json();
  }

  async function getCourse(courseId) {
    if (!courseId) return null;
    if (courseCache[courseId]) return courseCache[courseId];
    let c = null;
    for (const v of ["v3", "v2", "v1"]) {
      try { c = await api(`/${v}/courses/${courseId}`); break; } catch (e) { /* try older */ }
    }
    const out = c ? { course_code: c.courseId || "", course_name: c.name || "" }
                  : { course_code: domCourseCode(), course_name: clean(document.title) };
    courseCache[courseId] = out;
    return out;
  }

  function domCourseCode() {
    const m = (document.body ? document.body.innerText : "").match(/COMP\s?\d{4}(_\d{4})?/);
    return m ? m[0] : "";
  }

  async function listAll(path) {
    const out = [];
    let next = path + (path.includes("?") ? "&" : "?") + "limit=200";
    for (let guard = 0; next && guard < 20; guard++) {
      const data = await api(next);
      out.push(...(data.results || []));
      const np = data.paging && data.paging.nextPage;
      next = np ? np.replace(/^\/learn\/api\/public/, "") : null;
    }
    return out;
  }

  // Item title + folder titles, innermost first, by walking parentId.
  async function contentChain(courseId, contentId) {
    const chain = [];
    let id = contentId;
    for (let i = 0; id && i < 10; i++) {
      try {
        const c = await api(`/v1/courses/${courseId}/contents/${id}`);
        if (c.title && c.title !== "ROOT") chain.push(clean(c.title));
        id = c.parentId;
      } catch (e) { break; }
    }
    return chain;
  }

  // DOM fallback: labels of the clicked element's ancestors, innermost first.
  function domChain(el) {
    const out = [];
    for (let n = el, d = 0; n && d < 30; n = n.parentElement, d++) {
      const labels = [];
      const aria = n.getAttribute && n.getAttribute("aria-label");
      if (aria) labels.push(aria);
      if (n.querySelector) {
        const h = n.querySelector(":scope > h1, :scope > h2, :scope > h3, :scope > h4, :scope > header, :scope > [class*='title'], :scope > div > h3, :scope > div > h4, :scope > button[aria-expanded]");
        if (h && h.innerText) labels.push(h.innerText.split("\n")[0]);
      }
      for (const l of labels) {
        const t = clean(l);
        if (t && t.length > 2 && !out.includes(t)) out.push(t);
      }
    }
    return out.slice(0, 12);
  }

  // Every frame reports clicks; the background keeps the latest per tab.
  document.addEventListener("mousedown", (ev) => {
    const target = ev.target;
    const link = target.closest && target.closest("a, button, [role='button'], [role='link']");
    const click = {
      chain: domChain(target),
      item_title: clean(link ? link.innerText || link.getAttribute("aria-label") : ""),
      course_code: domCourseCode(),
    };
    try { chrome.runtime.sendMessage({ type: "click", click }); } catch (e) { /* extension reloaded */ }
  }, true);

  // Course from the URL + REST; item/folder chain from REST when the download URL names the content.
  async function contextFor(url) {
    const courseId = currentCourseId() || courseIdFrom(url);
    const course = (await getCourse(courseId)) || { course_code: domCourseCode(), course_name: "" };
    const m = (url || "").match(/contents\/(_\d+_\d+)/) || (url || "").match(/pid-(\d+)-dt/);
    let chain = [];
    if (courseId && m) {
      const cid = m[1].startsWith("_") ? m[1] : `_${m[1]}_1`;
      chain = await contentChain(courseId, cid);
    }
    return { ...course, rest_chain: chain };
  }

  async function listSections() {
    const courseId = currentCourseId();
    if (!courseId) return { error: "Open a Blackboard course page first." };
    const course = await getCourse(courseId);
    const top = await listAll(`/v1/courses/${courseId}/contents`);
    return { courseId, course, sections: top.map((c) => ({ id: c.id, title: clean(c.title), folder: !!c.hasChildren })) };
  }

  // The full item (body, handler details). The list endpoint does not always include the body, so every
  // item is fetched on its own - whatever its type - so nothing written in a page can be missed.
  async function fullItem(courseId, node) {
    if (typeof node.body === "string") return node;
    try {
      const full = await api(`/v1/courses/${courseId}/contents/${node.id}`);
      // keep what the list already said (link address, target) when the details leave it out
      return { ...node, ...full, contentHandler: { ...(node.contentHandler || {}), ...(full.contentHandler || {}) } };
    } catch (e) { return node; }
  }

  // Ask the server what a link really is (a link with no file extension can still be a PDF).
  async function probe(url) {
    try { return await chrome.runtime.sendMessage({ type: "probe", url }); } catch (e) { return null; }
  }

  // A text-only page (instructions written straight into Blackboard) saved as an .html file.
  function pageFile(courseId, node, html, ctx) {
    const title = clean(node.title) || "Page";
    const doc = `<!doctype html><html><head><meta charset="utf-8"><base href="${location.origin}/"><title>${title.replace(/</g, "&lt;")}</title>` +
      `<style>body{font-family:Segoe UI,Arial,sans-serif;max-width:860px;margin:32px auto;line-height:1.5;padding:0 16px}</style></head>` +
      `<body><h1>${title.replace(/</g, "&lt;")}</h1>${BBParse.resolve(html, location.origin)}</body></html>`;
    return { key: `${courseId}:page:${node.id}`, url: "data:text/html;charset=utf-8," + encodeURIComponent(doc),
             fileName: `${title.replace(/[<>:"/\\|?*\x00-\x1f]/g, "_").slice(0, 150)}.html`, ctx, page: true };
  }

  async function collect(courseId, sectionIds) {
    const course = await getCourse(courseId);
    const files = [];
    const skipped = [];
    const scanned = [];                            // every item looked at, shown in the popup
    const seen = new Set();
    const top = await listAll(`/v1/courses/${courseId}/contents`);
    const queue = top.filter((c) => sectionIds.includes(c.id)).map((c) => ({ node: c, chain: [] }));
    const visited = new Set();
    const tryList = (path) => listAll(path).catch(() => []);

    async function visit({ node, chain }) {
      const title = clean(node.title);
      // Ultra keeps a document's text and files in an internal "ultraDocumentBody" child: it stands for its parent.
      const junk = /^ultra\s*document\s*body/i.test(title);
      const shown = junk ? chain[0] || "Page" : title;
      const ctx = { ...course, item_title: junk ? "" : title, chain, source: "rest" };
      const innerChain = junk ? chain : [title, ...chain];
      const [item, kids, atts] = await Promise.all([
        fullItem(courseId, node),
        tryList(`/v1/courses/${courseId}/contents/${node.id}/children`),   // folders, modules, documents alike
        tryList(`/v1/courses/${courseId}/contents/${node.id}/attachments`)]);
      const handler = (item.contentHandler && item.contentHandler.id) || "";
      for (const k of kids) queue.push({ node: k, chain: innerChain });
      // A link to another item of the course: collect that item as well.
      const target = item.contentHandler && (item.contentHandler.targetId || item.contentHandler.target_id);
      if (target && !visited.has(target)) {
        try { queue.push({ node: await api(`/v1/courses/${courseId}/contents/${target}`), chain: innerChain }); } catch (e) { /* gone */ }
      }
      const mine = [];
      for (const a of atts) {
        mine.push({ key: `${courseId}:${a.id}`, url: `${API}/v1/courses/${courseId}/contents/${node.id}/attachments/${a.id}/download`,
                    fileName: a.fileName, ctx });
      }
      // Links written in the page itself: "Lecture 3: Designing architectures (slides, encoder, …)".
      const body = typeof item.body === "string" ? item.body : "";
      const extUrl = item.contentHandler && item.contentHandler.url;
      const html = body + (extUrl ? `<p><a href="${extUrl}">${title}</a></p>` : "");
      const { files: linked, skipped: notFiles } = BBParse.bodyLinks(html, location.origin);
      const linkCtx = (f) => ({ ...course, item_title: f.line || ctx.item_title, link_text: f.linkText, chain: innerChain, source: "rest" });
      for (const f of linked) mine.push({ key: `${courseId}:${f.url}`, url: f.url, fileName: f.fileName, ctx: linkCtx(f) });
      // Links with no file extension: ask the server (all at once); documents behind them are downloaded too.
      const probes = await Promise.all(notFiles.map((k) => /^https?:/i.test(k.href)
        ? probe(new URL(BBParse.resolve(k.href, location.origin), location.origin).href) : null));
      notFiles.forEach((k, n) => {
        const r = probes[n];
        if (r && r.file) {                          // named so the organiser knows its type: "Exam notes.pdf"
          const named = /\.[a-z0-9]{2,5}$/i.test(r.fileName || "") ? r.fileName : `${(k.text || r.fileName || "file").replace(/[<>:"/\|?*]/g, "_")}${r.ext || ""}`;
          mine.push({ key: `${courseId}:${r.url}`, url: r.url, fileName: named, ctx: linkCtx({ ...k, linkText: k.text }) });
        } else skipped.push({ ...k, section: shown, ctx: linkCtx({ ...k, linkText: k.text }) });
      });
      // Words written in the page (instructions, links to repositories...) but no file: keep the page itself.
      const words = body.replace(/<[^>]+>/g, " ").replace(/&nbsp;/g, " ").replace(/\s+/g, " ").trim();
      let page = false;
      if (!mine.length && words.length > 40 && !/folder/i.test(handler)) {
        // keyed by its place, so a document and its "ultraDocumentBody" give one page, not two
        mine.push({ ...pageFile(courseId, { ...item, title: shown }, body, junk ? { ...ctx, item_title: shown } : ctx),
                    key: `${courseId}:page:${innerChain.join("/")}` });
        page = true;
      }
      files.push(...mine);
      // An item with a link but nothing downloaded can still be added by hand in the popup.
      const link = !mine.length && (extUrl || (notFiles[0] && notFiles[0].href));
      if (!junk || mine.length) scanned.push({ title: shown, path: [...chain].reverse().join(" › "), files: mine.length, page,
        kind: handler.replace(/^resource\/x-bb-/, ""), add: link ? { href: link, text: title, ctx: { ...ctx, link_text: title } } : null });
    }

    // Several items at a time: each needs its details, children and attachments.
    let running = 0;
    await new Promise((done) => {
      const pump = () => {
        while (running < 6 && queue.length && visited.size < 3000) {
          const job = queue.shift();
          if (visited.has(job.node.id)) continue;
          visited.add(job.node.id);
          running++;
          visit(job).catch(() => {}).finally(() => { running--; pump(); });
        }
        if (!running) done();
      };
      pump();
    });
    return { files: files.filter((f) => !seen.has(f.key) && seen.add(f.key)), skipped, scanned };
  }

  chrome.runtime.onMessage.addListener((msg, sender, reply) => {
    if (window !== window.top) return false; // only the top frame answers
    if (!["context", "listSections", "collect"].includes(msg.type)) return false; // e.g. page-save messages
    const run = async () => {
      try {
        if (msg.type === "context") return await contextFor(msg.url);
        if (msg.type === "listSections") return await listSections();
        if (msg.type === "collect") return await collect(msg.courseId, msg.sectionIds);
      } catch (e) {
        return { error: String(e && e.message || e) };
      }
      return null;
    };
    run().then(reply);
    return true;
  });
})();
