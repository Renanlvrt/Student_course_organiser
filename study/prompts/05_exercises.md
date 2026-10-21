# Step 5: Exercise bank for one lecture (MANY exercises)

**Runner:** Claude Sonnet. **Unit:** one lecture.

## Inputs
- `{{MASTER_MD}}`, `{{CONCEPTS_JSON}}` and `{{TEACHING_JSON}}` for this lecture
- The practical sheets and their solutions linked to this lecture (markdown): {{PRACTICAL_MD_FILES}}
- An exam-style profile, built once per module from the past papers and mocks: `{{EXAM_PROFILE_MD}}`. It
  covers question formats, command words ("show that", "explain why", "compute"), mark distribution, typical
  lengths and what earns marks.
- Concepts the module says are **not examined**: {{NOT_EXAMINED}}

## Output → `{{OUT_DIR}}/{{LECTURE_STEM}} - exercises.json`
A JSON array of exercises:
```json
{"id": "L03.ex.017", "concepts": ["L03.lfsr"], "layer": "practical|drill|exam|transfer|interleaved",
 "difficulty": 1-5, "format": "mcq|numeric|short|compute|proof|explain|design|attack|code",
 "question": "markdown+LaTeX", "given": "data/values if any",
 "check": {"type": "exact|numeric|mcq|set|regex|none", "answer": "...", "tolerance": 0},
 "hints": ["nudge 1 (strategy)", "nudge 2 (first step)"],
 "solution": "complete worked solution, every step justified",
 "strategy": "how to recognise this type of question and the general method to attack it",
 "marks": 0, "mark_scheme": ["point → marks"], "common_mistakes": ["..."],
 "src": "practical 2 Q3 | based on Lecture 03 p.8 | 💡 new"}
```

Concepts marked `recap` in `{{PLAN_JSON}}` still get ≥1 interleaved question here, so revisited
ideas keep being practised.

## Required volume and spread (these are minimums, not targets)
- **Layer `practical`:** **every** question of every linked practical sheet, word for word, with the official
  solution if one exists. If none exists, write a full solution and mark it `💡 solution written by AI`.
- For **each concept**:
  - ≥ 3 **drill** questions (increasing difficulty; auto-checkable where possible).
  - ≥ 2 **exam**-style questions, written in the profile's style.
  - ≥ 1 **transfer** question: a format or angle the past papers never used (a twist, reversed direction, a new
    context, "spot the flaw", "design a variant", "explain to a beginner"). This is zero-shot practice, so the
    student doesn't overfit to old papers.
- ≥ 10 **interleaved** questions per lecture that mix this lecture's concepts with earlier lectures'.
- Concepts that past papers **never examined** get the same coverage as frequently examined ones.
- Every numeric or computational question gets a `check` the website can verify in JS. Use small, exact
  values that you have **recomputed step by step yourself**. Wrong answers in an answer key are unacceptable.

## Final self-check
Print `concept id | drill | exam | transfer` counts, the number of practical questions included compared
with the number on the sheets, and `answer keys recomputed: yes`.
