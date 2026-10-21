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

  // The page text (HTML body) of an item. The list endpoint does not always include it.
  async function bodyOf(courseId, node) {
    if (typeof node.body === "string") return node.body;
    const handler = (node.contentHandler && node.contentHandler.id) || "";
    if (!/document|lesson|ultra/i.test(handler) && !/^ultra\s*document\s*body/i.test(node.title || "")) return "";
    try { return (await api(`/v1/courses/${courseId}/contents/${node.id}`)).body || ""; } catch (e) { return ""; }
  }

  async function collect(courseId, sectionIds) {
    const course = await getCourse(courseId);
    const files = [];
    const skipped = [];
    const seen = new Set();
    const top = await listAll(`/v1/courses/${courseId}/contents`);
    const queue = top.filter((c) => sectionIds.includes(c.id)).map((c) => ({ node: c, chain: [] }));
    for (let guard = 0; queue.length && guard < 2000; guard++) {
      const { node, chain } = queue.shift();
      const title = clean(node.title);
      // Files embedded in Ultra documents sit under an internal "ultraDocumentBody" item: not a real title.
      const junk = /^ultra\s*document\s*body/i.test(title);
      const ctx = { ...course, item_title: junk ? "" : title, chain, source: "rest" };
      const innerChain = junk ? chain : [title, ...chain];
      if (node.hasChildren) {
        let kids = [];
        try { kids = await listAll(`/v1/courses/${courseId}/contents/${node.id}/children`); } catch (e) { /* hidden */ }
        for (const k of kids) queue.push({ node: k, chain: innerChain });
      } else {
        let atts = [];
        try { atts = await listAll(`/v1/courses/${courseId}/contents/${node.id}/attachments`); } catch (e) { /* none */ }
        for (const a of atts) {
          files.push({
            key: `${courseId}:${a.id}`,
            url: `${API}/v1/courses/${courseId}/contents/${node.id}/attachments/${a.id}/download`,
            fileName: a.fileName,
            ctx,
          });
        }
      }
      // Links written in the page itself: "Lecture 3: Designing architectures (slides, encoder, …)".
      const { files: linked, skipped: notFiles } = BBParse.bodyLinks(await bodyOf(courseId, node), location.origin);
      for (const f of linked) {
        files.push({
          key: `${courseId}:${f.url}`, url: f.url, fileName: f.fileName,
          ctx: { ...course, item_title: f.line || ctx.item_title, link_text: f.linkText,
                 chain: junk ? chain : [title, ...chain], source: "rest" },
        });
      }
      for (const k of notFiles) skipped.push({ ...k, section: title });
    }
    return { files: files.filter((f) => !seen.has(f.key) && seen.add(f.key)), skipped };
  }

  chrome.runtime.onMessage.addListener((msg, sender, reply) => {
    if (window !== window.top) return false; // only the top frame answers
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
