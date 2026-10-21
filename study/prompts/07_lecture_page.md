# Step 7: Build one lecture's page

**Runner:** Claude Sonnet. **Unit:** ONE lecture (one at a time, so nothing is forgotten).
**Inputs:** `{{MASTER_MD}}`, `{{CONCEPTS_JSON}}`, `{{TEACHING_JSON}}`, `{{EXERCISES_JSON}}`, the site shell in
`{{SITE_DIR}}` (read `ARCHITECTURE.md` first and reuse its components; don't fork them).

Write `{{SITE_DIR}}/lectures/{{NN}}-{{SLUG}}.html` (+ `js/lectures/{{NN}}.js` for its visuals).

Use the **creating-explainers** skill's figure and voice guidance for every concept section (hand-built,
steppable Canvas/SVG figures, conversational but precise prose) and **frontend-design** for visual quality.
Its output format is replaced by our shell's components, so the result is part of the site, not a separate
single page.

## Page structure (in this order)
1. **Map:** what this lecture answers, the concepts in learning order, and the earlier concepts it needs (links).
2. **One section per concept, in `learning_order`:**
   - hook → explanation (everything from the teaching entry, maths in KaTeX) → analogies (with "where it
     breaks") → the source's worked examples → new examples
   - **Animation** (`Stepper`), built exactly from the storyboard
   - **Sandbox** (`Sandbox`), running the real algorithm, with its challenge
   - misconceptions → exam tips → 2–3 quick-check exercises inline
   - a `[src: … p.N]` footnote linking to the PDF page (`../../Lectures/{{PART}}/…pdf#page=N`)
3. **Recall:** this lecture's flashcards.
4. **Practice:** every exercise for this lecture, filterable by layer, concept and difficulty.
5. **Summary sheet:** a one-screen, printable recap of every definition, formula and algorithm.

## Quality bar
- The visuals must look **excellent**, not generic: purposeful colour (the same colour means the same
  thing throughout, e.g. key = amber, plaintext = blue, ciphertext = red), smooth transitions, clear labels,
  and readable at a glance. Use SVG for diagrams and Canvas for anything that animates a lot of elements.
- Every sandbox output is **correct**. Add a tiny self-test in the JS (known input → known output) that runs on
  load and logs a failure to the console.
- For `hero_visual` concepts, leave a clearly marked slot `<div data-hero="{{id}}">`. The anatomy skill fills it
  in a later pass.

## Done when
Open the page headlessly, with no console errors and every self-test passing. Then print
`concept id | explanation ✓ | analogy ✓ | example ✓ | animation ✓ | sandbox ✓ | exercises n`. Every
concept in the inventory must appear, with every column ticked.
