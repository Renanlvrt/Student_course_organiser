# Step 9: Tracked knowledge file (coursework modules, e.g. DLCV)

**Runner:** Antigravity (Gemini Argon, long context). **Unit:** a whole module, updated **incrementally**.

Goal: one file that can be handed to any AI so that it knows **everything** in the course: every lecture
concept, every reading, every notebook. This lets it help with the coursework at the level of someone who
attended everything.

## Output → `courses\{{MODULE}}\{{MODULE}}_KNOWLEDGE.md`
```
# {{MODULE_NAME}}: course knowledge base
## Manifest            (tracked: one row per source → file | sha256 | pages | added | last updated)
## How to use this file (for an AI: notation, scope, what the coursework asks, citation format)
## Concept index        (every concept id → one line + where it is defined below)
## Lectures             (per lecture: the full content of its audited master notes, condensed only where
                         wording repeats; every definition, formula, algorithm, hyperparameter and result kept)
## Readings             (per paper: problem, method, key equations, architecture, training details, results,
                         limitations, and which lecture concepts it relates to)
## Code & notebooks     (per notebook: what it does, key functions, shapes, hyperparameters, how to reuse it)
## Coursework brief     (requirements, marking criteria, constraints, deadlines; verbatim where it matters)
## Cross-links          (concept → lectures, readings, notebooks, practicals)
```

## Rules
- **Incremental and tracked:** read the Manifest first. Process only sources whose sha256 is new or has
  changed. Update their sections in place, then update the Manifest row. Never drop a section whose source
  still exists.
- The content comes from the **audited master notes** (Step 3 PASS), not from fresh summarising, so nothing is
  lost again. Readings and notebooks are captured page by page with the same rules as Step 2.
- Keep it as one markdown file, with stable headings and ids, so it is easy to parse. If it exceeds ~400k
  tokens, also write `{{MODULE}}_KNOWLEDGE_index.md` (the Concept index + Manifest only), which tells an AI which
  section to load.

Print the Manifest diff (added / updated / unchanged) when finished.
