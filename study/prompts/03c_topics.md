# Step 3c: Group the lecture into teaching topics

**Runner:** Claude Sonnet. **Unit:** one lecture. Small and fast: you only read the concept inventory.

The full notes, glossary and flashcards already cover **every** concept. The expensive teaching material
(animations, interactive sandboxes, videos, worked teaching text) is built per **topic**, not per concept, so
choose topics the way a great lecturer plans a revision session.

## Task
Group this lecture's concepts into **2 to 5 topics** (2 for a light lecture, 5 only for a dense one). Each
topic is one idea a student must truly understand: a construction, an attack, a theorem with its proof, a
security notion. Every concept id belongs to exactly one topic. Order topics in teaching order.

For each topic decide:
- `hard`: true if a student probably does not already know it (proofs, reductions, security games,
  constructions with several moving parts, probability arguments). At most 2 hard topics per lecture.
- `prior`: `new`, or `extends <earlier topic id>` if it deepens a topic from an earlier lecture (then only the
  new aspects are taught), or `recap <earlier topic id>` if it adds nothing new (no visuals are built).

Earlier topics in this part:
{{EARLIER_TOPICS}}

## Output
Between `<<<TOPICS` and `TOPICS>>>`, a JSON list:
```json
[{"id": "{{LECTURE_ID}}.t1", "title": "Short, plain title", "concepts": ["{{LECTURE_ID}}.x", "..."],
  "hard": false, "prior": "new", "why": "one sentence: what the student must be able to do"}]
```

## Concept inventory
{{CONCEPTS}}
