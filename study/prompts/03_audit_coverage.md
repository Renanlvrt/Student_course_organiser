# Step 3: Independent coverage audit

**Runner:** Claude Sonnet in a fresh session (independent of step 2), one pass. **Unit:** one lecture.

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

## Output (edits only: do NOT reprint the notes)
Reply with one JSON object between `<<<AUDIT` and `AUDIT>>>`:
```json
{"missing": [{"src": "<file stem> p.5", "item": "what the source has", "page": 5,
              "text": "the markdown to add, complete and faithful, ending with [src: <file stem> p.5]"}],
 "edits": [{"find": "an exact, unique snippet of the candidate notes (copy it character for character)",
            "replace": "the corrected text", "why": "distorted | unsupported | other"}],
 "concepts_missing": [{"id": "{{LECTURE_ID}}.<slug>", "name": "...", "kind": "...", "summary": "...", "src": ["..."]}],
 "verdict": "PASS if nothing is missing or distorted, else FIX"}
```
- `missing`: every examinable item the notes lose. The pipeline inserts `text` into the notes at that page.
- `edits`: each distortion corrected, and each unsupported statement either marked `> 💡 Added:` or removed.
  `find` must occur exactly once in the candidate notes; keep it short (one sentence or formula).
- Only list real problems. Do not rephrase correct text and do not flag correct derivations that are already
  marked as additions. If everything is right, return empty lists and `"verdict": "PASS"`.

## Sources
{{SOURCES}}

## Candidate master notes
<<<CANDIDATE
{{MASTER}}
CANDIDATE>>>

## Candidate concept inventory
{{CONCEPTS}}
