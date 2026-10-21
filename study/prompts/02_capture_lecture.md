# Step 2: Capture one lecture completely (master notes + concept inventory)

**Runner:** long-context model (default: Antigravity, Gemini Argon High). **Unit:** ONE lecture.

## Inputs
- The lecture's markdown sources (often slides plus a handout; use all of them): {{LECTURE_MD_FILES}}
- Related sections of the full lecture notes, if the module has them: {{NOTES_MD_SECTIONS}}
- Readings attached to this lecture: {{READING_MD_FILES}}
- The concept inventory of previous lectures (for links, not for re-capturing): {{PREVIOUS_CONCEPTS_JSON}}

## Task A: Master notes → `{{OUT_DIR}}/{{LECTURE_STEM}} - Master.md`
Go through **every page of every source in order**. For each page, write a section
`### p.N: <slide title or first line>` that contains **everything** on that page, rewritten as clear notes:
- Definitions in a `**Definition (name).**` block, theorems and lemmas likewise, then the proof steps in
  full. Number each step and keep each step's justification.
- Algorithms as numbered steps **and** pseudocode, with their inputs, outputs and complexity if given.
- Worked examples with **every number** kept, and the arithmetic shown step by step.
- Every remark, caveat, "why this matters", attack, historical note and reading pointer.
- `[src: …]` trace on every block.

When a handout or the full notes add detail to a slide, merge it in at that point and trace it to both
sources. When sources disagree, keep both and add `> ⚠ Check:`.

At the end, add a **"Connections"** section: which earlier concepts this lecture relies on, and which ones it
extends.

## Task B: Concept inventory → `{{OUT_DIR}}/{{LECTURE_STEM}} - concepts.json`
A JSON array. One object per **atomic** concept (one idea a student could be examined on). Split compound
ideas: "OTP" is not one concept. Its definition, perfect secrecy proof, key-reuse attack and key-length bound
are four.
```json
{"id": "L02.otp-key-reuse", "name": "...", "kind": "definition|theorem|proof|algorithm|construction|attack|property|example|fact|notation",
 "summary": "one precise sentence", "formulas": ["$...$"], "depends_on": ["L01.xor"], "src": ["Lecture 02 - ... p.7"],
 "examinable_signals": ["stated as 'important'", "has worked example", "appears in practical 2"]}
```

## Task C: Self-audit (do not skip)
Re-read each source page and tick it against the notes. Then print exactly this table and nothing else:
`page | items on page | items captured | missing (list)`. Every row must have *missing* empty. If not, fix
the notes and reprint the table.
