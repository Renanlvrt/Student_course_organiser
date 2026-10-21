# Step 6: Website shell (once per part)

**Runner:** Claude Sonnet. **Unit:** one part. Output folder: `{{SITE_DIR}}` (= `courses\{{MODULE}}\Website\{{PART}}\`).

Build the frame that every lecture page plugs into. Use the **frontend-design** skill to choose a distinctive,
deliberate look (typography, colour system, spacing) rather than a templated default. Write the chosen
colour meanings into `ARCHITECTURE.md` so that every lecture page reuses them. Plain **HTML + CSS + vanilla JS**: no build step, no
framework, and it opens directly from disk (`file://`). Chrome blocks `fetch()` of local files and
`<script type="module">` over `file://`, so:
- **Use no ES modules and no `fetch`.** Use classic `<script src>` only.
- Data ships as `.js` files that set globals, generated from the pipeline's JSON:
  `data/L03.js` → `window.COURSE.lectures["L03"] = {concepts, teaching, exercises}`. The same applies to mocks
  and the course map. Libraries may only be vendored copies inside
`{{SITE_DIR}}/vendor/` (KaTeX is required, for maths).

## Must contain
- `index.html`: the course map. Each lecture is a card showing its concepts, progress % and "weak topics".
  A dependency map of concepts across lectures is drawn as an interactive graph.
- **Navigation:** one tab per lecture (in course order) plus tabs for **Practicals**, **Recall**, **Exercise
  gym**, **Mock exams**, **Weak topics**. Lecture tabs open `lectures/<NN>-<slug>.html`.
- `js/core.js` shared components:
  - `Stepper`: an animation player with play/pause/step/back/speed and a caption per frame.
  - `Sandbox`: a frame with inputs, live outputs and a challenge with a success state.
  - `Exercise`: renders exercise JSON, auto-checks via `check`, shows hints one at a time and reveals the
    solution after an attempt or on request.
  - `AskClaude`: a button that copies a marking prompt ("Mark my answer to this exam question out of N using
    this mark scheme…" + question + mark scheme + my answer) to the clipboard. **No API keys anywhere.**
  - `Cards`: active-recall flashcards with spaced repetition (SM-2-style intervals).
  - `Progress`: every attempt is stored in `localStorage`. A wrong answer adds the concept to Weak topics and
    schedules a re-ask. Includes export and import as JSON, so progress survives a browser wipe.
- A design that is calm and readable for long sessions, with light and dark themes, keyboard navigation (←/→
  between sections, space to play/pause animations), print-friendly CSS and a mobile layout.
- `ARCHITECTURE.md`: the file tree, the data flow (JSON → pages), the component APIs and how to add a lecture.

Print the file tree and confirm that `index.html` opens **from `file://`** with no console errors. Test with
headless Chrome. The anatomy skill's `scripts/drive.mjs` already drives it over CDP and can report console
messages.
