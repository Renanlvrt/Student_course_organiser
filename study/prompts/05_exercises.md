# Step 5: Exercise bank for one lecture (MANY exercises)

**Runner:** Claude Sonnet. **Unit:** one lecture.

## Inputs
- `{{MASTER_MD}}`, `{{CONCEPTS_JSON}}` and `{{TEACHING_JSON}}` for this lecture
- The practical sheets and their solutions linked to this lecture (markdown): {{PRACTICAL_MD_FILES}}
- An exam-style profile, built once per module from the past papers and mocks: `{{EXAM_PROFILE_MD}}`. It
  covers question formats, command words ("show that", "explain why", "compute"), mark distribution, typical
  lengths and what earns marks.
- Concepts the module says are **not examined**: {{NOT_EXAMINED}}

## Output
A JSON array of exercises between `<<<JSON` and `JSON>>>`:
```json
{"id": "L03.ex.017", "concepts": ["L03.lfsr"], "layer": "practical|drill|exam|transfer|interleaved",
 "difficulty": 1-5, "format": "mcq|numeric|short|compute|proof|explain|design|attack|code",
 "question": "markdown+LaTeX", "given": "data/values if any",
 "options": ["only for mcq: the choices, markdown+LaTeX"],
 "check": {"type": "exact|numeric|mcq|set|regex|none", "answer": "for mcq: the 0-based index of the right option", "tolerance": 0},
 "hints": ["nudge 1 (strategy)", "nudge 2 (first step)"],
 "solution": "complete worked solution, every step justified",
 "strategy": "how to recognise this type of question and the general method to attack it",
 "marks": 0, "mark_scheme": ["point → marks"], "common_mistakes": ["..."],
 "src": "practical 2 Q3 | based on Lecture 03 p.8 | 💡 new"}
```

Exercises are organised by **topic** (see the topics below): put the topic id first in `concepts`, then any
concept ids the question uses. Topics marked `recap` get only interleaved questions.

## Required volume and spread (these are minimums, not targets)
- **Layer `practical`:** **every** question of every linked practical sheet, word for word, with the official
  solution if one exists. If none exists, write a full solution and mark it `💡 solution written by AI`.
- For **each topic** (not each concept: keep the bank focused):
  - ≥ 3 **drill** questions (increasing difficulty; auto-checkable where possible).
  - ≥ 2 **exam**-style questions, written in the profile's style.
  - ≥ 1 **transfer** question: a format or angle the past papers never used (a twist, reversed direction, a new
    context, "spot the flaw", "design a variant", "explain to a beginner"). This is zero-shot practice, so the
    student doesn't overfit to old papers.
- ≥ 10 **interleaved** questions per lecture that mix this lecture's topics with earlier lectures'.
- Across the topics, every **examinable concept** of the inventory is used by at least one question, and
  hard topics get extra drill and exam questions. The student wants to train a lot: more is better than fewer.
- Keep each exercise compact (no padding in solutions) so many fit in one reply.
- Concepts that past papers **never examined** get the same coverage as frequently examined ones.
- Every numeric or computational question gets a `check` the website can verify in JS. Use small, exact
  values that you have **recomputed step by step yourself**. Wrong answers in an answer key are unacceptable.

## Final self-check
Print `topic id | drill | exam | transfer` counts, the number of practical questions included compared
with the number on the sheets, and `answer keys recomputed: yes`.

## Topics (step 3c)
{{PLAN}}

## Concept inventory
{{CONCEPTS}}

## Teaching design
{{TEACHING}}

## Master notes
{{MASTER}}

## Practical sheets
{{PRACTICALS}}

## Exam profile
{{EXAM_PROFILE}}
