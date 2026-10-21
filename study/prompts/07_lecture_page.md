# Step 7: Build one lecture's visuals (animations + sandboxes)

**Runner:** Claude Sonnet. **Unit:** ONE lecture.

The site shell already renders everything textual from the pipeline data: explanations, analogies, examples,
misconceptions, exam tips, the full audited notes, flashcards and every exercise. **Your only job is the
visuals:** one file, `visuals/{{LECTURE_ID}}.js`, that registers an **animation** and a **sandbox** for every
concept the plan marks `all` or `aspects`. Recap concepts need none.

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
  `C.muted`, `C.rule`, `C.tint`. **No purple or violet.** The page is white.
- CSS helpers you can use: `.bits` (+ `.key` / `.plain` / `.cipher`) containing `<i>` cells for bit strings,
  `<button>`, `<button class="primary">`, `<input>`, `<select>`.
- SVG uses a `viewBox` so it scales. Labels are ≥ 13px at 640px wide. It must look good at 360px wide (mobile).

## Rules
- Build each animation **exactly from its storyboard** in the teaching data: every frame, in order. A frame
  shows *what changes*: highlight the moving part, keep the rest still, and give each frame one clear caption.
- Every sandbox runs the **real** computation (real XOR, real LFSR, real modular arithmetic with BigInt,
  real probability), never canned outputs. It has the challenge from the teaching data and calls
  `api.solved()` when the goal is reached.
- For every computation you implement, add **at least one `Study.selftest`** with a known input and output,
  taken from the lecture's worked examples when one exists.
- Write plain, readable functions. Share helpers inside the file (e.g. one `lfsrStep` used by the animation,
  the sandbox and the self-test).
- The file must not throw at load time, even if a concept id is missing from the page.

## Output
Reply with the complete file between `<<<VISUALS_JS` and `VISUALS_JS>>>`, then a table:
`concept id | animation frames | sandbox | self-tests`. Every `all` / `aspects` concept must be listed.

## Plan (step 3b)
{{PLAN}}

## Teaching design (storyboards are in `animation` and `sandbox`)
{{TEACHING}}

## Concept inventory
{{CONCEPTS}}
