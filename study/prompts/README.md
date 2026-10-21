# Revision pipeline prompts

These replace the three 2025 prompts ("prompt reading pdf", "prompt website", "prompt new exercises").
Every prompt is run with `00_rules.md` prepended and its `{{placeholders}}` filled in by the pipeline.

Default `--runner claude`: **Claude Code runs every step** (Sonnet; the audit uses Opus so it is an independent,
stronger check). `--runner agy` or `auto` (Antigravity for content, Claude for visuals) remain as opt-in fallbacks. Publish for the phone: `python -m study publish <Module>`.

| # | Prompt | Unit | Default runner | Skills used |
|---|---|---|---|---|
| 0 | *(local script)* PDF → markdown with `<!-- page N -->` markers; flags bad pages | each PDF | local, free | — |
| 1 | `01_fix_pages.md`: rewrite flagged pages from the page image | each PDF | Antigravity · Gemini Argon | — |
| 1b | `01b_map_notes.md`: assign every page of whole-module notes to a lecture (or "unassigned", captured too) | each notes PDF | Antigravity · Gemini Argon | — |
| 2 | `02_capture_lecture.md`: master notes + concept inventory, page by page | **one lecture** | Antigravity · Gemini Argon High | — |
| 3 | `03_audit_coverage.md`: independent "did we lose anything?" audit, looped until PASS | one lecture | **different** model from step 2: Antigravity · Claude Sonnet (Google quota) | `fact-checking-explainers` |
| 3b | `03b_merge_registry.md`: merge into the part's concept registry; decide teach all / only new aspects / recap | one lecture | Antigravity · Gemini Argon High | — |
| 4 | `04_teaching_plan.md`: explanation, analogies, examples, animation + sandbox storyboards, recall cards | one lecture | Antigravity · Gemini Argon High | `generating-stem-flashcards` (cards) |
| 5 | `05_exercises.md`: practical questions + drill/exam/transfer/interleaved, MANY | one lecture | Antigravity · Gemini Argon High | — |
| 6 | `06_site_shell_SUPERSEDED.md`: replaced by the hand-built shell in `study/site_template` | — | — | `frontend-design` |
| 7 | `07_lecture_page.md`: one lecture's page with every visual | one lecture | **Claude Code** · Sonnet | `creating-explainers`, `frontend-design` |
| 7b | hero visuals: fill the `data-hero` slots | 2–3 per part | **Claude Code** · Sonnet | `anatomy` |
| 7c | videos (optional): only concepts with a `video` storyboard | rare | Claude Code | `manim-skill` (`/manim-skill:manim-video`) |
| 8 | `08_mock_exams.md`: exam profile, coverage matrix, mocks | once per part | Antigravity · Gemini Argon High | — |
| 9 | `09_knowledge_file.md`: tracked `<Module>_KNOWLEDGE.md` for coursework modules | module, incremental | Antigravity · Gemini Argon | — |

**Scalable:** when new lectures arrive, step 3b compares them with the part's concept registry. A concept
already taught in detail only gets a recap link. A concept that was only mentioned or partly covered before
and is now explained in detail gets the full treatment, or just its missing aspects, and older pages link
forward to it.

**Why it can't miss information:**
- Capture goes one lecture at a time and page by page (step 2), with a self-audit table at the end.
- A second model with a fresh context then re-reads the source and must find nothing missing or distorted
  (step 3, repeated until PASS).
- Every later step builds from the audited notes. Its own completion table must list every concept id
  (steps 4, 5, 7).

**Skills installed (2026-10-21).**
- Claude Code (`~/.claude-account1`): explain-this plugin (3 skills), manim-skill plugin, `anatomy`,
  `flashcards`, `frontend-design`.
- Antigravity (`~/.gemini/antigravity/skills`): `anatomy`, `flashcards`, `frontend-design`,
  `creating-explainers`, `fact-checking-explainers`, `explaining-codebases`.
- manim's Python dependencies are installed only when the first video is needed
  (`manim-skill/scripts/install.ps1`).
