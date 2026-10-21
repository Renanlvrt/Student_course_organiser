# Step 1b: Map whole-module notes onto lectures (only when the module has them)

**Runner:** long-context model (default: Antigravity, Gemini Argon). **Unit:** one notes document, e.g. Crypto's
`Other\Full Lecture Notes 2025-26.pdf`.

Without this step, anything that appears only in the notes would fall outside every per-lecture capture and
audit.

## Inputs
- Notes markdown, with `<!-- page N -->` markers: `{{NOTES_MD}}` (pages 1..{{NOTES_PAGES}})
- The slide titles of every lecture (first heading of each page): {{LECTURE_OUTLINES}}

## Output → `{{OUT_DIR}}/notes-map.json`
```json
{"pages": {"1": "front", "2": "L01", "3": "L01", "14": ["L02", "L03"], "60": "unassigned"},
 "unassigned_reason": {"60": "topic not in any lecture so far (likely a future lecture)"}}
```
- Every page from 1 to {{NOTES_PAGES}} appears **exactly once** as a key. A page that spans two lectures
  lists both.
- `front`: title page, contents, preface. These are still captured, in a short "About the notes" section.
- `unassigned`: content that matches no lecture yet. It is captured as its own unit
  (`Notes - unassigned - Master.md`) with Step 2's rules, and re-mapped when new lectures arrive.

The pipeline then checks that the keys are exactly 1..{{NOTES_PAGES}}, and passes each lecture its pages as
`{{NOTES_MD_SECTIONS}}` in Step 2.
