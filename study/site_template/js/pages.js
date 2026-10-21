/* Page logic: course map (index.html), one lecture (lecture.html?id=L01), practice (practice.html?tab=…). */
(function () {
  "use strict";
  const S = window.Study, h = S.h;
  const params = new URLSearchParams(location.search);
  const main = () => document.querySelector("main");

  const lectureFiles = () => COURSE.lectures.flatMap((l) => ["data/" + l.id + ".js"]);
  const allExercises = () => Object.values(window.LECTURES || {}).flatMap((l) => (l.exercises || []).map((e) => Object.assign({ lecture: l.id }, e)));
  const allCards = () => Object.values(window.LECTURES || {}).flatMap((l) => (l.teaching || []).flatMap((t) =>
    (t.recall_cards || []).map((c, k) => Object.assign({ id: t.id + ".card" + k, concept: t.id }, c))));
  const conceptName = (id) => { for (const l of Object.values(window.LECTURES || {})) for (const c of l.concepts || []) if (c.id === id) return c.name; return id; };
  const conceptVideos = (id) => Object.values(window.LECTURES || {}).flatMap((l) => (l.videos || []).filter((v) => v.concept === id));
  const conceptLecture = (id) => { for (const l of Object.values(window.LECTURES || {})) if ((l.concepts || []).some((c) => c.id === id)) return l.id; return null; };

  /* ---------------------------------------------------------------- index.html */
  function renderIndex() {
    const m = main();
    m.replaceChildren(
      h("div", { class: "read" },
        h("h1", {}, COURSE.part),
        h("p", { class: "lede" }, COURSE.module + " (" + COURSE.code + "). Every lecture, taught concept by concept, with something to watch, something to play with and plenty to practise."),
        h("h2", {}, "Lectures"),
        h("ol", { class: "map" }, COURSE.lectures.map((l) => {
          const data = (window.LECTURES || {})[l.id];
          const ids = (data ? data.concepts : []).map((c) => c.id);
          const st = ids.map(S.progress.status);
          const good = st.filter((s) => s === "good").length, weak = st.filter((s) => s === "weak").length;
          return h("li", {}, h("a", { class: "tile", href: "lecture.html?id=" + l.id },
            h("span", { class: "dot " + (weak ? "weak" : good === ids.length && ids.length ? "good" : good ? "seen" : "") }),
            h("span", { class: "name" }, l.title),
            h("span", { class: "tag" }, ids.length ? good + " of " + ids.length + " concepts mastered" + (weak ? ", " + weak + " weak" : "") : "not built yet")));
        })),
        h("h2", {}, "Today"),
        todayBox()));
  }
  function todayBox() {
    const cards = allCards(), due = S.srs.due(cards).length, weak = S.progress.weak();
    return h("div", { class: "ui actions" },
      h("a", { class: "btn" + (due ? " primary" : ""), href: "practice.html?tab=recall" }, due ? due + (due === 1 ? " flashcard is due" : " flashcards are due") : "Flashcards (none due)"),
      h("a", { class: "btn", href: "practice.html?tab=weak" }, weak.length ? weak.length + " weak topics to revisit" : "Weak topics (none yet)"),
      h("a", { class: "btn", href: "practice.html?tab=gym" }, allExercises().length + " exercises in the gym"));
  }

  /* ---------------------------------------------------------------- lecture.html */
  function renderLecture(id) {
    const L = (window.LECTURES || {})[id], meta = COURSE.lectures.find((l) => l.id === id);
    const m = main();
    if (!L || !meta) { m.replaceChildren(h("h1", {}, "Not built yet"), h("p", {}, "Run the pipeline for this lecture, then rebuild the site.")); return; }
    document.title = meta.title + " | " + COURSE.module;
    const teach = Object.fromEntries((L.teaching || []).map((t) => [t.id, t]));
    const plan = Object.fromEntries(((L.plan && (L.plan.concepts || L.plan)) || []).map((p) => [p.id, p]));
    const order = (L.concepts || []).slice().sort((a, b) => ((teach[a.id] || {}).learning_order || 99) - ((teach[b.id] || {}).learning_order || 99));
    const exs = L.exercises || [];
    const tabs = { learn: "Learn", notes: "Full notes", glossary: "Glossary", cards: "Flashcards", practice: "Practice (" + exs.length + ")" };
    const panes = {};
    const tabBar = h("div", { class: "tabs", role: "tablist" }, Object.entries(tabs).map(([k, label]) =>
      h("button", { role: "tab", "aria-selected": k === "learn" ? "true" : "false", onclick: () => select(k), "data-k": k }, label)));
    function select(k) {
      tabBar.querySelectorAll("button").forEach((b) => b.setAttribute("aria-selected", b.dataset.k === k ? "true" : "false"));
      for (const [pk, p] of Object.entries(panes)) p.hidden = pk !== k;
      if (!panes[k].dataset.ready) { fill[k](panes[k]); panes[k].dataset.ready = "1"; }
      history.replaceState(null, "", "?id=" + id + (k === "learn" ? "" : "&tab=" + k));
    }
    const fill = {
      learn(p) {
        p.append(h("ol", { class: "map read" }, order.map((c) => h("li", {}, h("span", { class: "dot " + ({ good: "good", weak: "weak", seen: "seen" }[S.progress.status(c.id)] || "") }),
          h("a", { href: "#" + cssId(c.id) }, c.name), h("span", { class: "tag" }, recapOf(c.id) ? "recap" : c.kind || "")))));
        for (const c of order) p.append(conceptSection(c, teach[c.id], plan[c.id], exs));
        observeSeen(p);
      },
      notes(p) { p.append(h("div", { class: "read notes" }, S.mdEl("div", L.master || "Master notes not built yet."))); },
      glossary(p) {
        const seen = new Map();
        for (const c of order) for (const g of (teach[c.id] || {}).glossary || []) {
          const k = String(g.term || "").toLowerCase();
          if (k && !seen.has(k)) seen.set(k, Object.assign({ concept: c }, g));
        }
        const terms = [...seen.values()].sort((a, b) => String(a.term).localeCompare(String(b.term)));
        p.append(h("div", { class: "read" }, terms.length ? glossaryList(terms, true) : h("p", { class: "muted" }, "No glossary yet for this lecture.")));
      },
      cards(p) {
        const cards = (L.teaching || []).flatMap((t) => (t.recall_cards || []).map((c, k) => Object.assign({ id: t.id + ".card" + k }, c)));
        const mount = h("div", { class: "read" }); p.append(mount); S.cardSession(cards, mount);
      },
      practice(p) { p.append(exerciseBrowser(exs)); }
    };
    function recapOf(cid) { const pl = plan[cid]; return pl && (pl.teach === "recap" || pl.action === "recap") ? pl : null; }
    for (const k of Object.keys(tabs)) panes[k] = h("div", { role: "tabpanel", hidden: true });
    m.replaceChildren(h("div", { class: "read" }, h("p", { class: "kind" }, COURSE.part + " · " + id), h("h1", {}, meta.title.replace(/^Lecture \d+ - /, "")),
      L.summary ? S.mdEl("p", L.summary, "lede") : ""), tabBar, ...Object.values(panes));
    select(params.get("tab") && tabs[params.get("tab")] ? params.get("tab") : "learn");
    if (location.hash) setTimeout(() => { const t = document.getElementById(location.hash.slice(1)); if (t) t.scrollIntoView(); }, 50);
  }
  const cssId = (id) => "c-" + String(id).replace(/[^A-Za-z0-9_-]/g, "-");
  function glossaryList(terms, withLinks) {
    return h("dl", { class: "glossary" }, terms.flatMap((g) => [
      h("dt", {}, S.mdEl("span", g.term), withLinks && g.concept ? h("a", { class: "from ui", href: "#" + cssId(g.concept.id), onclick: () => { const b = document.querySelector('.tabs [data-k="learn"]'); if (b) b.click(); } }, g.concept.name) : ""),
      h("dd", {}, S.mdEl("div", g.plain || g.definition || ""), g.formal ? S.mdEl("div", "**Formally:** " + g.formal, "formal") : "")]));
  }

  function conceptSection(c, t, pl, exs) {
    t = t || {};
    const sec = h("section", { class: "concept", id: cssId(c.id), "data-concept": c.id });
    const hard = t.hard || (t.difficulty || 0) >= 4;
    sec.append(h("p", { class: "kind" }, c.kind || ""), h("h2", {}, c.name, hard ? h("span", { class: "hardtag ui" }, "Hard concept") : ""));
    const teachMode = pl ? (pl.teach || pl.action || "all") : "all";
    if (teachMode === "recap") {
      const home = pl.home || (window.REGISTRY && REGISTRY[c.id] && REGISTRY[c.id].home);
      sec.append(h("div", { class: "recap" }, S.mdEl("div", c.summary || ""),
        home ? h("p", { class: "ui" }, h("a", { href: "lecture.html?id=" + home + "#" + cssId(c.id) }, "Explained in full in " + home)) : ""));
    } else {
      if (t.hook) sec.append(S.mdEl("p", t.hook, "hook"));
      if (Array.isArray(teachMode)) sec.append(S.mdEl("p", "This lecture adds: " + teachMode.join(", ") + ".", "muted ui"));
      if ((t.glossary || []).length) sec.append(h("div", { class: "words read" }, h("p", { class: "ui label" }, "Words to know"), glossaryList(t.glossary, false)));
      if (t.intuition) sec.append(h("div", { class: "intuition read" }, S.mdEl("div", "**The idea in plain words.** " + t.intuition)));
      sec.append(S.mdEl("div", t.explanation || c.summary || "", "read"));
      for (const a of t.analogies || []) {
        const text = typeof a === "string" ? a : a.analogy || a.text || "";
        const br = typeof a === "string" ? "" : a.breaks || a.where_it_breaks || "";
        sec.append(h("div", { class: "analogy read" }, S.mdEl("div", text), br ? S.mdEl("span", "Where it breaks: " + br, "breaks") : ""));
      }
      for (const e of t.examples || []) sec.append(h("div", { class: "example read" }, S.mdEl("div", typeof e === "string" ? e : e.text || e.example || JSON.stringify(e))));
      for (const tb of t.tables || []) sec.append(h("div", { class: "table read" }, S.mdEl("div", typeof tb === "string" ? tb : (tb.title ? "**" + tb.title + "**\n\n" : "") + (tb.markdown || ""))));
      const vis = S.visuals[c.id] || {};
      for (const fg of vis.figures || []) sec.append(S.figure(fg));
      if (t.animation || vis.animation) sec.append(S.stepper(Object.assign({ title: (t.animation || {}).title }, vis.animation || {})));
      for (const an of vis.animations || []) sec.append(S.stepper(an));
      if (t.sandbox || vis.sandbox) sec.append(S.sandbox(Object.assign({ title: (t.sandbox || {}).title, challenge: (t.sandbox || {}).challenge }, vis.sandbox || {}), c.id));
      for (const vid of conceptVideos(c.id)) sec.append(h("figure", { class: "film" }, h("video", { src: vid.file, controls: "", playsinline: "", preload: "metadata" }),
        h("figcaption", { class: "ui" }, vid.kind === "notebooklm" ? vid.title : "Short film: " + (vid.title || c.name))));
      if (t.hero_visual) sec.append(h("div", { "data-hero": c.id }));
      for (const mstk of t.misconceptions || []) sec.append(S.mdEl("div", "**Common misconception.** " + (typeof mstk === "string" ? mstk : JSON.stringify(mstk)), "mistake read"));
      for (const tip of t.exam_tips || []) sec.append(S.mdEl("div", "**Exam tip.** " + tip, "tip read"));
    }
    const quick = exs.filter((e) => (e.concepts || []).includes(c.id) && e.layer === "drill").slice(0, 2);
    if (quick.length) { sec.append(h("h3", {}, "Quick check")); quick.forEach((e) => sec.append(h("div", { class: "read" }, S.exercise(e)))); }
    if (c.src) sec.append(h("p", { class: "src" }, "Source: " + [].concat(c.src).join("; ")));
    return sec;
  }
  function observeSeen(root) {
    if (!("IntersectionObserver" in window)) return;
    const io = new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) { S.progress.seen(e.target.dataset.concept); io.unobserve(e.target); } }), { threshold: 0.4 });
    root.querySelectorAll(".concept").forEach((s) => io.observe(s));
  }

  /* ---------------------------------------------------------------- exercise browser (lecture practice + gym) */
  function exerciseBrowser(list, preset) {
    preset = preset || {};
    const wrap = h("div", { class: "read" });
    const sel = (label, key, values, names) => h("label", {}, label + " ",
      h("select", { onchange: (e) => { f[key] = e.target.value; draw(); } }, [h("option", { value: "" }, "all")]
        .concat(values.map((v) => h("option", { value: v, selected: preset[key] === v }, names ? names(v) : v)))));
    const f = Object.assign({ layer: "", concept: "", difficulty: "", lecture: "" }, preset);
    const uniq = (xs) => [...new Set(xs.filter(Boolean))];
    const layers = uniq(list.map((e) => e.layer));
    const concepts = uniq(list.flatMap((e) => e.concepts || []));
    const lectures = uniq(list.map((e) => e.lecture));
    const out = h("div");
    const filters = h("div", { class: "filters" },
      lectures.length > 1 ? sel("Lecture", "lecture", lectures) : "",
      sel("Type", "layer", layers), sel("Concept", "concept", concepts, conceptName),
      sel("Difficulty", "difficulty", ["1", "2", "3", "4", "5"]),
      h("button", { onclick: () => { const xs = filtered(); shuffle(xs); out.replaceChildren(...xs.slice(0, 10).map((e) => S.exercise(e))); } }, "Shuffle 10"));
    function filtered() {
      return list.filter((e) => (!f.layer || e.layer === f.layer) && (!f.concept || (e.concepts || []).includes(f.concept)) &&
        (!f.difficulty || String(e.difficulty) === f.difficulty) && (!f.lecture || e.lecture === f.lecture) &&
        (!preset.only || preset.only(e)));
    }
    function draw() {
      const xs = filtered();
      out.replaceChildren(h("p", { class: "muted ui" }, xs.length + " exercises"), ...xs.slice(0, 60).map((e) => S.exercise(e)),
        xs.length > 60 ? h("p", { class: "muted ui" }, "Showing the first 60. Narrow the filters to see the rest.") : "");
    }
    wrap.append(filters, out); draw();
    return wrap;
  }
  function shuffle(a) { for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } }

  /* ---------------------------------------------------------------- practice.html */
  function renderPractice(tab) {
    const m = main();
    const titles = { recall: "Flashcards", gym: "Exercise gym", weak: "Weak topics", mocks: "Mock exams", progress: "Save or restore progress" };
    m.replaceChildren(h("h1", { class: "read" }, titles[tab] || "Practice"));
    if (tab === "recall") { const mount = h("div", { class: "read" }); m.append(mount); S.cardSession(allCards(), mount); }
    else if (tab === "gym") m.append(exerciseBrowser(allExercises()));
    else if (tab === "weak") {
      const weak = new Set(S.progress.weak());
      if (!weak.size) m.append(h("p", { class: "read" }, "Nothing weak yet. Any concept you get wrong appears here until you answer it right twice in a row."));
      else {
        m.append(h("ul", { class: "read ui" }, [...weak].map((id) => h("li", {}, h("a", { href: "lecture.html?id=" + conceptLecture(id) + "#" + cssId(id) }, conceptName(id))))));
        m.append(exerciseBrowser(allExercises(), { only: (e) => (e.concepts || []).some((c) => weak.has(c)) }));
      }
    } else if (tab === "mocks") {
      const mocks = window.MOCKS || [];
      m.append(mocks.length ? h("div", { class: "read" }, mocks.map((mk) => mockBlock(mk)))
        : h("p", { class: "read" }, "Mock exams are generated once every lecture in this part has been built."));
    } else if (tab === "progress") {
      const ta = h("textarea", { style: "width:100%;min-height:8rem", "aria-label": "Progress data" });
      m.append(h("div", { class: "read ui" },
        h("p", {}, "Your progress is stored in this browser. Copy it somewhere safe, or paste a saved copy to restore it."),
        h("button", { class: "primary", onclick: () => { ta.value = S.progress.exportJSON(); S.copy(ta.value); } }, "Copy my progress"),
        " ", h("button", { onclick: () => { try { S.progress.importJSON(ta.value); S.toast("Progress restored."); } catch (e) { S.toast("That text is not saved progress."); } } }, "Restore from the text below"),
        h("p", {}, ta)));
    }
  }
  function mockBlock(mk) {
    const box = h("section", { class: "concept" }, h("h2", {}, mk.title || mk.id), S.mdEl("p", mk.instructions || "", "muted"));
    let start = null, timer = null;
    const clock = h("span", { class: "ui" });
    const begin = h("button", { class: "primary", onclick: () => {
      start = Date.now(); begin.remove(); qs.hidden = false;
      timer = setInterval(() => { const left = (mk.minutes || 120) * 60e3 - (Date.now() - start);
        clock.textContent = left > 0 ? "Time left: " + Math.floor(left / 60e3) + " min" : "Time is up."; if (left <= 0) clearInterval(timer); }, 1000);
    } }, "Start the timed mock (" + (mk.minutes || 120) + " min)");
    const qs = h("div", { hidden: true }, (mk.questions || []).map((q) => S.exercise(q)));
    box.append(begin, clock, qs);
    return box;
  }

  /* ---------------------------------------------------------------- boot */
  S.boot = function (page) {
    const extra = page === "lecture" ? ["data/" + params.get("id") + ".js", "visuals/" + params.get("id") + ".js"] : lectureFiles();
    S.loadScripts(["data/registry.js", "data/mocks.js"].concat(extra)).then(() => {
      const active = page === "lecture" ? params.get("id") : page === "practice" ? params.get("tab") || "gym" : null;
      if (page === "index") renderIndex();
      else if (page === "lecture") renderLecture(params.get("id"));
      else renderPractice(params.get("tab") || "gym");
      S.nav(active);
    });
  };
})();
