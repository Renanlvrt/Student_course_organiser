# Step 3b: Merge a lecture into the module's concept registry (incremental growth)

**Runner:** Claude Sonnet. **Unit:** one newly captured (and audited) lecture.
This step makes the site **scalable**. New lectures add to it, and nothing is explained twice.

## Inputs
- The module registry: `{{REGISTRY_JSON}}` (= `Lectures\{{PART}}\lectures_markdown\registry.json`; empty for the first
  lecture)
- The new lecture's audited `{{CONCEPTS_JSON}}` and `{{MASTER_MD}}`

## The registry: one entry per concept across the whole part
```json
{"id": "otp", "name": "One-time pad", "home": "L02",
 "depth": "full|partial|mention",
 "aspects": {"definition": "L02", "perfect-secrecy-proof": "L02", "key-reuse-attack": "L03"},
 "appearances": [{"lecture": "L02", "depth": "full", "src": ["… p.7-9"]}, {"lecture": "L05", "depth": "mention", "src": ["… p.3"]}],
 "taught_at": {"L02": ["definition", "perfect-secrecy-proof"], "L03": ["key-reuse-attack"]}}
```
- **depth**, judged against the source:
  - `full`: explained in detail (definition plus mechanism/proof/example).
  - `partial`: some aspects only.
  - `mention`: named or used without explanation.
- **aspects**: the separate examinable parts of a concept (definition, construction, proof, attack, example,
  complexity, …), each with the lecture that explains it **in detail**.

## Rules for each concept in the new lecture
1. **New concept:** add it. `home` = this lecture.
2. **Known concept, and the new lecture adds nothing beyond what is already taught in detail:** record the
   appearance only. The new lecture page shows a short **recap card** linking to the home section, with
   no re-explanation.
3. **Known concept, and the new lecture explains aspects not yet taught in detail** (e.g. it was only
   mentioned before, or a new proof, variant or attack): teach **only those aspects** in the new lecture
   (`taught_at.<new>` = the new aspects). If the concept was previously only a `mention` or `partial` and is
   now explained in full, the full explanation lives in the new lecture. The old lecture's section then links
   forward to it ("explained in full in Lecture N").
4. **Never drop anything:** even a mention-only appearance stays in the registry, so the cross-links stay
   complete.

## Output
Emit three blocks: `<<<REGISTRY` … `REGISTRY>>>` (the full updated registry), `<<<PLAN` … `PLAN>>>` and
`<<<BACKLINKS` … `BACKLINKS>>>`:
- The updated registry.
- `{{OUT_DIR}}/{{LECTURE_STEM}} - plan.json`: for each concept of this lecture, `teach: all | aspects:[…] | recap`.
  Steps 4, 5 and 7 build **only** what the plan says. Exercises are still written for every concept the
  lecture touches, so practice keeps mixing old and new.
- `{{OUT_DIR}}/{{LECTURE_STEM}} - backlinks.json`: the earlier lecture pages that need a "see also / explained
  in full in…" link added. Step 7 applies them.

Print a table: `concept | before (depth) | now (depth) | action`.

## Current registry
{{REGISTRY}}

## New lecture `{{LECTURE_ID}}`: concept inventory
{{CONCEPTS}}

## New lecture: master notes
{{MASTER}}
