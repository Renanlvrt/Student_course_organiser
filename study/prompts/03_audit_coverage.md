# Step 3: Independent coverage audit

**Runner:** a DIFFERENT model or session from Step 2 (default: Claude Sonnet). It gets a fresh context
on purpose, so it cannot "remember" what it meant to write. **Unit:** one lecture.

## Inputs
- Source markdown: {{LECTURE_MD_FILES}} (+ {{NOTES_MD_SECTIONS}})
- Candidate master notes: `{{MASTER_MD}}`
- Concept inventory: `{{CONCEPTS_JSON}}`

## Task
Act as a strict examiner looking for anything the notes lose. Apply the **fact-checking-explainers** skill's
discipline: every checkable claim traces to a source, is corrected, or is cut.

For **each source page, in order**, list every examinable item on it: each definition, claim, formula, number,
step, example, figure detail and caveat. Then check that each item is in the master notes **with the same
meaning** and is represented by a concept in the inventory.

Also check the other direction. For each statement in the notes that is not marked `💡 Added`, confirm a
source supports it.

## Output
First the audit between `<<<AUDIT` and `AUDIT>>>`:
```json
{"missing": [{"src": "... p.5", "item": "exact quote or description", "fix": "text to insert", "after_heading": "### p.5: ..."}],
 "distorted": [{"src": "...", "notes_say": "...", "source_says": "...", "fix": "..."}],
 "unsupported": [{"notes_say": "...", "fix": "mark as 💡 Added or delete"}],
 "concepts_missing": [{"name": "...", "src": "..."}],
 "verdict": "PASS only if all four lists are empty"}
```
Then apply every fix yourself and emit the **complete corrected** master notes between `<<<MASTER_MD` and
`MASTER_MD>>>`, and the complete corrected inventory between `<<<JSON` and `JSON>>>`. If the verdict is
PASS, emit them unchanged. The verdict refers to the state **before** your fixes. The pipeline repeats this step until the verdict is PASS, for **at most 3
rounds**. After that, the lecture is marked `needs human`, with the remaining items listed, so that a
looping audit can't burn through usage limits.

## Sources
{{SOURCES}}

## Candidate master notes
<<<CANDIDATE
{{MASTER}}
CANDIDATE>>>

## Candidate concept inventory
{{CONCEPTS}}
