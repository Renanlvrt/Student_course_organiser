# Step 7: Build one lecture's visuals (animations + sandboxes)

**Runner:** Claude Sonnet. **Unit:** ONE lecture.

The site shell already renders everything textual from the pipeline data: explanations, analogies, examples,
misconceptions, exam tips, the full audited notes, flashcards and every exercise. **Your only job is the
visuals:** one file, `visuals/{{LECTURE_ID}}.js`, that registers for every concept the plan marks `all` or
`aspects` (recap concepts need none):
- the main **animation** (its `animation` storyboard), plus one per `extra_animations` storyboard;
- one **drawing** per `figures` entry;
- the **sandbox**.

This is what the student learns from, so it must be excellent: think of the best motion-graphics explainers
(3Blue1Brown, Bartosz Ciechanowski's explorable explanations). The bar for every visual: a student who has
never met the idea understands it from the visual and its captions alone.

Use the **creating-explainers** skill's figure guidance (hand-built, steppable SVG/Canvas figures that show the
mechanism) and **frontend-design** for visual quality.

## The API (classic script; no `fetch`, no ES modules, no libraries: the site runs from `file://`)
```js
Study.visuals["L03.lfsr"] = {
  animation: {                       // rendered by Study.stepper: Back / Next step / Play / speed / ← → keys
    frames: [
      { caption: "markdown + $LaTeX$ shown under the stage",
        render(stage, C, i) { stage.append(Study.svg("svg", {viewBox: "0 0 640 220"}, /* … */)); } },
      // or { caption, svg: "<svg …>…</svg>" }
    ]
  },
  animations: [ { title: "Walking through the proof", frames: [ /* same shape as animation */ ] } ],   // extra_animations
  figures: [ { title: "The CPA game", caption: "markdown caption", render(stage, C) { /* static SVG drawing */ } } ],
  sandbox: {                         // rendered by Study.sandbox; its challenge text comes from the teaching data
    build(stage, api, C) {           // api.h(tag, attrs, ...kids), api.svg(...), api.md(text), api.math(el), api.solved(msg)
      /* inputs → live outputs; call api.solved() when the challenge goal is reached */
    }
  }
};
Study.selftest("LFSR degree-4 example", () => lfsrRun([0,1,1,0], [1,1,0,0], 10).join("") === "0110101111" || "wrong output");
```
- `C` holds the colour tokens. Use them with **one meaning each**, never raw hex: `C.plain` / `C.plainTint` =
  plaintext and inputs, `C.key` / `C.keyTint` = keys, seeds and secrets, `C.cipher` / `C.cipherTint` =
  ciphertext and outputs (and "wrong"), `C.ok` = correct, `C.teal` = structure and highlights, `C.ink`,
  `C.muted`, `C.rule`, `C.tint`. **No purple or violet.** The page is light (off-white); colours are soft Apple-style system hues, never pure primaries.
- CSS helpers you can use: `.bits` (+ `.key` / `.plain` / `.cipher`) containing `<i>` cells for bit strings,
  `<button>`, `<button class="primary">`, `<input>`, `<select>`.
- SVG uses a `viewBox` so it scales. Labels are ≥ 13px at 640px wide. It must look good at 360px wide (mobile).

## Motion: how to make frames move (built into the stepper)
- **Magic move:** give every shape that persists between frames the same `data-k` attribute
  (`Study.svg("rect", {"data-k": "bit3", …})`). When the student steps, each keyed shape glides from its old
  position, size, colour and opacity to the new one; shapes that are new in a frame fade in. So build each frame
  as a complete still picture of that moment, and key the parts that move: bits sliding into a register, a key
  XOR-ing onto a message, a ciphertext block travelling to the adversary, a probability bar growing.
- Inside a frame you may add your own motion with the Web Animations API (`el.animate(...)`, 300–900 ms, an
  ease-out curve) for emphasis: a pulse on the bit that just changed, a stroke being drawn, a counter ticking.
  Check `Study.reducedMotion()` and skip decorative motion when it is true.
- Motion has a job: it shows cause and effect. Nothing moves without a reason, and the caption says what just
  happened.

## Drawing quality
- Build real diagrams, not boxes of text: registers as rows of cells, games as two lanes (challenger and
  adversary) with arrows carrying messages, key spaces as grids of dots, distributions as bars, trees for
  probability, number lines for modular arithmetic.
- Label everything in the drawing (≥ 13px at 640px wide), with LaTeX labels via `<foreignObject>` or plain
  text for symbols. Use generous whitespace, aligned grids, rounded corners (rx 6–10), 1.5–2px strokes.
- Colour = meaning (below), with tints for fills and full colour for strokes and text. Highlight the one thing
  each frame is about; mute the rest (`C.muted`, lower opacity).

## Rules
- Build each animation **exactly from its storyboard** in the teaching data: every frame, in order. A frame
  shows *what changes*: highlight the moving part, keep the rest still, and give each frame one clear caption.
- Every sandbox runs the **real** computation (real XOR, real LFSR, real modular arithmetic with BigInt,
  real probability), never canned outputs. It has the challenge from the teaching data and calls
  `api.solved()` when the goal is reached.
- Sandboxes are playgrounds, not forms: sliders, toggles, clickable bits and draggable values, with the
  output redrawn live as a picture (not just a number), plus a reset button. Show the intermediate steps.
- For every computation you implement, add **at least one `Study.selftest`** with a known input and output,
  taken from the lecture's worked examples when one exists.
- Write plain, readable functions. Share helpers inside the file (e.g. one `lfsrStep` used by the animation,
  the sandbox and the self-test).
- The file must not throw at load time, even if a concept id is missing from the page.

## Output
Reply with the complete file between `<<<VISUALS_JS` and `VISUALS_JS>>>`, then a table:
`concept id | animations (frames each) | figures | sandbox | self-tests`. Every `all` / `aspects` concept must be listed.

## Plan (step 3b)
{{PLAN}}

## Teaching design (storyboards are in `animation` and `sandbox`)
{{TEACHING}}

## Concept inventory
{{CONCEPTS}}
