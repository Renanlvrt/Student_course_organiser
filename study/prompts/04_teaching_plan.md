# Step 4: Teaching design for one lecture

**Runner:** Claude Sonnet (Claude Code, or Sonnet inside Antigravity when Claude limits are high).
**Unit:** one lecture. **Inputs:** the audited `{{MASTER_MD}}` and `{{CONCEPTS_JSON}}`.

Follow `{{PLAN_JSON}}` (step 3b): `all` = full treatment; `aspects:[…]` = teach only those aspects and link to the
concept's home section for the rest; `recap` = only a short recap card + link (no animation/sandbox needed).

Design **how each concept will be taught**, before any HTML is written. Emit a JSON array between `<<<JSON` and
`JSON>>>`, with one entry per concept id (every id, none skipped):

```json
{"id": "L03.lfsr",
 "learning_order": 4,
 "hook": "the question this concept answers, in one sentence",
 "explanation": "clear, complete explanation in markdown+LaTeX, faithful to the master notes; nothing from the notes left out",
 "analogies": ["2+ real-world analogies; each says exactly where the analogy breaks"],
 "examples": ["the source's worked examples, verbatim with numbers", "2+ NEW examples with full working (💡 Added)"],
 "misconceptions": ["typical wrong belief → why it is wrong"],
 "animation": {"title": "...", "what_moves": "step-by-step storyboard: frame 1 shows..., frame 2...", "controls": "play/pause/step/back/speed",
               "makes_clear": "the one insight a student gets by watching"},
 "sandbox": {"title": "...", "inputs": "what the student can change (keys, bits, taps, sizes...)", "outputs": "what updates live",
             "challenge": "a goal to reach inside the sandbox, e.g. 'find a tap set with maximal period'", "correctness": "must compute the real algorithm, not fake it"},
 "hero_visual": false,
 "video": null,
 "recall_cards": [{"front": "...", "back": "...", "layer": "recall|understanding|boundaries"}],
 "exam_tips": ["how this concept is typically examined, what markers look for, traps"]}
```

## Rules for recall cards
Follow the **generating-stem-flashcards** skill: cards are atomic, use all 3 layers (recall / understanding /
boundaries) and LaTeX for maths. Every concept gets **≥ 3 cards**, with at least one in each layer that applies.

## Rules for the visuals
- **Every concept** gets one animation **and** one sandbox. For a pure definition, animate an example of it and
  let the sandbox test membership (e.g. "is this scheme perfectly secret? change the distributions and see").
- Sandboxes run the **real** computation in JS (real XOR, real LFSR, real modular arithmetic with BigInt). The
  numbers shown must be correct.
- Set `hero_visual: true` on the 2–3 concepts per *part* that are most structural (constructions, protocols,
  pipelines). These are rendered later with the `anatomy` skill as a working machine.
- Set `video` to a short storyboard **only** for a proof or derivation that a narrated video explains better
  than an interaction (Manim, optional).

At the end, print the concept ids with their animation and sandbox titles, and confirm the count equals the number of concepts in the inventory.

## Plan (step 3b)
{{PLAN}}

## Concept inventory
{{CONCEPTS}}

## Master notes
{{MASTER}}
