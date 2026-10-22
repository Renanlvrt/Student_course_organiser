# Step 4: Teaching design for one lecture (per topic)

**Runner:** Claude Sonnet on Claude Code. **Unit:** one lecture, one call.
**Inputs:** the audited master notes, the concept inventory and the lecture's 2–5 **topics** (step 3c).

The full notes already show every concept, so nothing is lost. Your job is to **teach**: design how each topic
will be taught, and write the lecture's glossary and flashcards. Be rich where it matters and brief where it
doesn't. Each topic's teaching covers all the concepts listed in it.

Reply with one JSON object between `<<<JSON` and `JSON>>>`:

```json
{"glossary": [{"term": "negligible function", "plain": "everyday meaning a first-year student gets at once",
               "formal": "the course's exact definition in LaTeX [src: …], or empty if the course gives none"}],
 "cards": [{"concept": "L03.lfsr", "front": "...", "back": "...", "layer": "recall|understanding|boundaries"}],
 "concept_notes": {"L03.lfsr": "2-4 sentences that explain this concept in plain words, with its key formula or example"},
 "topics": [
  {"id": "L03.t2", "learning_order": 2, "hook": "the question this topic answers, in one sentence",
   "terms": ["glossary terms this topic uses"],
   "intuition": "the idea in plain words, before any formalism (2–4 sentences, an image to hold in mind)",
   "explanation": "markdown + LaTeX that teaches the whole topic step by step, faithful to the notes",
   "analogies": [{"analogy": "...", "breaks": "where it stops working"}],
   "examples": ["the source's worked example, with every intermediate value", "one NEW example (💡 Added)"],
   "tables": [{"title": "...", "markdown": "| … | … |\n|---|---|\n| … | … |"}],
   "figures": [{"title": "...", "draws": "exactly what to draw: boxes, arrows, labels, colours by meaning"}],
   "animation": {"title": "...", "what_moves": "frame 1 shows …, frame 2 …", "makes_clear": "the one insight"},
   "extra_animations": [],
   "sandbox": {"title": "...", "inputs": "what the student changes", "outputs": "what redraws live",
               "challenge": "a goal to reach", "correctness": "the real computation it runs"},
   "video": null,
   "misconceptions": ["wrong belief → why it is wrong"],
   "exam_tips": ["how this is examined, what markers reward, traps"]}]}
```

## Rules
- **Glossary: define every word** the lecture uses that a student might not know (terms, symbols,
  abbreviations, "polynomial time", "uniformly at random", "oracle", "mod"…). One entry per term, short.
- **Cards**: 2 per concept in the inventory (every concept id), atomic, LaTeX for maths, mixing the three
  layers across the lecture. Follow the generating-stem-flashcards skill.
- **Topics**: one entry per topic id given, in teaching order. `prior: extends …` → teach only the new aspects
  and say what is assumed; `prior: recap …` → only `hook`, a short `explanation` and `exam_tips` (no visuals).
- **concept_notes: explain every concept** of the inventory (every id), 2–4 sentences each, plain words first.
- **Visuals are only for the hard topics** (`hard: true`): one `animation`, one `sandbox` (runs the real
  computation in JS) and one `figure`. Every other topic: leave `animation`, `sandbox`, `figures` and
  `extra_animations` empty, and teach it with the explanation, examples and a `table` where useful.
- `video` is always `null` (videos are made separately).
- Keep it tight: no repetition between the explanation, concept_notes and cards.
- Faithful to the notes and in the course's notation; anything you add is marked `💡 Added`.

## Topics (step 3c)
{{TOPICS}}

## Concept inventory
{{CONCEPTS}}

## Master notes
{{MASTER}}
