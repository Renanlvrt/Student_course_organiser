# Revision pipeline: requirements (from Renan, 2026-10-21)

The organiser already sorts every download into `courses\<Module>\{Lectures,Practicals,Website,Other}\<Part>\`.
This file covers what happens **after** sorting: turning a module's files into a website that teaches and trains me.
This is a record of what I asked for. Open questions are at the bottom and are filled in as I answer.

## How I revised last year (the workflow to automate and improve)
1. Organise every file into folders (now done by the organiser).
2. Convert every PDF into a Markdown file, with one `.md` per PDF in a Markdown folder for the lectures.
3. In Antigravity, give Gemini Pro (or the new model) a prompt to read **all** the markdowns.
   Gemini's rate limits were much looser than Sonnet's, so Gemini did the heavy reading.
4. With that knowledge, Gemini writes **analogies, examples and exercises**.
5. Claude Sonnet, still in Antigravity, builds a **whole website** from it: a guided course that teaches the
   whole module.
6. Old prompts (for reference): `Desktop\Durham\Theory_of_computation\Model of computation\before turing\`
   `prompt reading pdf`, `prompt website.txt`, `prompt new exercises`. Example output:
   `Desktop\Durham\Theory_of_computation\websites\website_*` (plain HTML/CSS/JS, ARCHITECTURE.md, sidebar,
   one page per module). I will also give a newer prompt later, to be merged with this file.

## What the website must be
- **Covers everything, misses nothing.** The site is split per source file: each lecture/file gets its own
  navigation tab containing *everything* in that file, followed by the next tab (next lecture/chapter).
- **One website per submodule (part)**, which also covers that part's practicals.
  It lives in `courses\<Module>\Website\<Part>\`.
- **Lots of visualisation**: illustrations, diagrams and animations, often interactive.
- **Rule: every concept gets at least one animation/visualiser AND at least one interactive environment** I can
  play with. Examples:
  - Crypto: every cryptographic method (keys, ciphers, …).
  - AADS: hashing, cuckoo hashing, universal hashing, …
- **Analogies and examples** for each concept (analogies are how I learn best).

## Exercises and exam training (the most important part)
- **Lots of exercises**, personalised to *this module's content and this exam*, not generic ones.
- Teach **how to solve** them: the best strategy, tips, common traps and general exam tips.
- Train me to get the best result in the exam.
- Use the practicals where they are good. Where there aren't enough exercises, generate **efficient,
  exam-style** ones grounded in the lecture content.

## Constraints already known
- Gemini API key: the `GEMINI_API_KEY` user env var only. Never in files, never pushed.
- Layout from the organiser's SPEC.md (Lectures / Practicals / Website / Other per module, parts Term 1/2 etc.).

## Answers, round 1 (2026-10-21)
- **Automate it here**, but I choose the runner for each job: **Claude Code** (`claude -p`) or
  **Antigravity** (`agy -p`). **No API keys.** Both CLIs use my subscriptions/logins.
  - Use the right model for each job. **Sonnet** builds the website and explains concepts in the best way.
  - Worry: Claude Code usage might run out. Antigravity may be better for heavy jobs.
  - **Track my usage limits in both** and pick based on them.
- **PDF → Markdown:** convert locally to markdown first, then look at the PDF page itself **only where the
  markdown is poorly parsed** (maths, diagrams, tables). Don't send every page as an image.
- **Visuals must be extremely good.** Use existing skills where they help (list below), or better ones.
- **Exercises:**
  - Do **all** the practical exercises (with solutions).
  - Study the **past papers / mock exam question style**.
  - **Don't overfit to past exams. Train for zero-shot.** Use varied question styles that keep the core exam
    style, and add questions on lecture concepts the past papers/mocks never asked about.
  - Also produce **mock exams**.
- **Pilot module: Crypto** (COMP3731).

## Tooling facts (checked on this laptop, 2026-10-21)
- `claude` 2.1.306. Headless runs with `-p --output-format stream-json --verbose` emit a
  `rate_limit_event` with `five_hour` and `seven_day` utilisation (e.g. 0.39 / 0.21), so Claude usage is trackable.
- `agy` 1.4.4 (Antigravity CLI). It has `-p` print mode, `--model`, `--output-format json` and
  `--json-schema`. Models include Gemini 4 Argon (low/med/high), Gemini 3.8 Flash and **Claude Sonnet 5.5 / Opus 5.5**,
  so Sonnet can run on the Antigravity quota.
  - The first headless probe timed out at 90s while an MCP server (StitchMCP) was still connecting. To fix later:
    a trusted workspace, and possibly MCP disabled for batch runs.
  - It has a quota manager internally. How to read the remaining quota is still to be found.
- Installed locally: ffmpeg, MiKTeX (LaTeX), PyMuPDF, node. Not installed: manim, pymupdf4llm.

## Skills reviewed (GitHub, 2026-10-21)
| Skill | What it is | Verdict |
|---|---|---|
| analyticalmonk/explain-this (22★) | Distill-style interactive HTML explainers with hand-built Canvas figures, plus a **fact-checking gate** (every claim traced to the source) | **Use.** It's closest to "one visualiser + one interactive per concept", and the fact-check enforces "miss nothing / invent nothing" |
| wheresryan22/anatomy (18k★, Oct 2026) | Very polished interactive isometric SVG/WebGL figures that build an idea as a working machine. Also runs in Antigravity | **Use for a few hero visuals** per part (e.g. an AES round as a machine). Too slow for every concept |
| jalliet/flashcards (15★) | Atomic flashcards in 3 layers (recall / understanding / boundaries), KaTeX, Anki export | **Use** for a recall layer next to the exercises |
| vumichien/manim-skill (7★) | 4-agent pipeline that produces Manim **videos** (.mp4) | Optional. Videos aren't interactive, it's slow, and it needs manim installed. Only for proofs that suit a video |
| TIGER-AI-Lab/TheoremExplainAgent | Research code for long theorem videos | No (research benchmark, heavy) |
| programmersd21/EfficientManim | Standalone node-based Manim IDE | No (a separate app, not an agent skill) |
| theinternetfolks/visual-cues | A company's internal explainer pages (has an `interactive-explainer-guide` SKILL.md) | No, but its guide's "logic-faithful explainer vs static visualiser" rule is worth borrowing |

## Answers, round 2 (2026-10-21)
- **Visuals: interactive web + a few videos.**
  - Every concept gets **≥1 step-through animation** and **≥1 interactive sandbox**, built in Canvas/SVG/JS
    in the explain-this style and passing its fact-check gate.
  - Each part gets 2–3 **anatomy** hero visuals.
  - **Manim videos** only for proofs/derivations that really suit a video.
- **Runner: automatic based on limits, and I can override.**
  - Reading/extraction runs on Antigravity (Gemini Argon).
  - The website and explanations run on **Sonnet**: through Claude Code while my 5-hour/weekly Claude usage is
    under a threshold, otherwise Sonnet inside Antigravity.
  - A status panel shows both limits, and I can force either runner.
- **Marking and progress on the website:**
  - **Auto-check** wherever an answer can be checked (numbers, MCQ, small computations such as an RSA step).
  - **Progress + spaced review.** Remember wrong answers, keep a weak-topics list, bring questions back later
    (stored in the browser).
  - **Ask-Claude button.** Copy the question and my answer into a ready-made marking prompt for Claude/Gemini.
    The site contains no API key.
  - Full solutions and mark schemes are still shown after an attempt, because the solving strategy is the point.
    Self-marking against them is optional. Ask-Claude is there for real marking of written answers.
- **Markdown location:** inside the Lectures folder, `courses\<Module>\Lectures\<Part>\lectures_markdown\`.
  - One `.md` per lecture **and** per practical/exercise sheet.
  - The organiser must leave this folder alone (no moving, no duplicate removal).
- **Maths must stay understandable.** Maths is written as LaTeX (`$…$`, `$$…$$`) and rendered with KaTeX on the
  site. Pages where local extraction garbles the maths are re-read from the PDF page by the agent (see the
  hybrid conversion below).

## Design decisions that follow
- **PDF → Markdown (hybrid, my suggestion):**
  1. Convert locally and for free with PyMuPDF (`pymupdf4llm`), which keeps headings, lists, tables and code.
  2. A checker flags poorly parsed pages: maths glyphs or broken symbols, little text compared with the page
     area, large figures or diagrams, garbled tables.
  3. The agent opens **only the flagged pages** as images and rewrites them: maths in LaTeX, each diagram
     described in words with its labels, tables rebuilt.
  4. Each `.md` keeps `<!-- page N -->` markers, so every concept traces back to a PDF page (needed for the
     "miss nothing" check).
  - If local extraction proves too weak, the fallback is MinerU (local, has formula recognition).
- **Exercise layers (no overfitting):**
  1. Every practical exercise, reworked with a full solution and the strategy behind it.
  2. Questions in exam style on **every** lecture concept, especially those the past papers/mocks never asked.
  3. Transfer questions: new formats and twists on the same ideas (zero-shot practice).
  4. Timed mock exams with mark schemes.
  5. A recall layer of flashcards (jalliet/flashcards style, 3 layers).
- **Coverage guarantee:** a concept inventory (`concepts.json`) is extracted per file. The build only counts
  as complete when every concept has an explanation, an analogy, an example, an animation, an interactive
  sandbox and at least one exercise. A checker script verifies this.

## Still to come from me
- ~~My newer prompt~~ → given in round 3, merged into `study/prompts/`.

## Round 3 (2026-10-21): the old prompts, and what the new ones must do better
- The 3 old prompts were given (reading PDFs → learning plan, website, 5×15 mock questions). They are outdated.
  The new chain is in `study/prompts/`.
- **The most important rule: don't miss a single piece of information from the lectures. Not a SINGLE one.**
  Work page by page and one lecture at a time, so nothing is forgotten.
- Visualisers and interactive elements for every concept: I'm a visual learner and need to learn every concept
  as efficiently as possible.
- Practice with **active recall** and **MANY exercises**.
- **Coursework modules (e.g. Deep Learning):** keep a **tracked knowledge file** that can be given to an AI.
  It holds everything from every lecture, concept and additional reading, so the AI is as good as it can be.
  → `09_knowledge_file.md`, with a manifest of sources and hashes for incremental updates.
- **Install the visualisation/interactive skills** (done, see `study/prompts/README.md`).

## Round 4 (2026-10-21)
- **Papermorph** (DozenTwelve/Papermorph, 812★): judged **not to install**. It makes narrated lesson films for
  watching, and its skill selects "the ideas, examples and sections to teach", which breaks the "miss
  nothing" rule. It is also heavy (an intake conversation, TTS per chapter) and tuned for Opus. We borrow only
  its idea of formulas and diagrams changing step by step with captions, which our Stepper already does.
- **UI colours: white background plus other colours. NO purple.** Written into `06_site_shell.md`.
- **Scalable growth:** when more lectures arrive, add only what isn't already on the site. Track how deeply
  every concept has been explained:
  - Explained in detail already → don't re-explain (recap + link).
  - Explained only briefly before and in detail now → explain it in detail now.
  - Already detailed but the new lecture adds aspects → explain only the missing parts.
  - → `03b_merge_registry.md` (registry with depth and aspects per concept).
- Antigravity works interactively for me ("Reply Ok" → "Ok"). **Go ahead with implementation.**
- Headless `agy -p` still never starts a turn (3 attempts, 0 events). Gemini CLI needs a one-time
  browser login (`gemini`). Until one of them works headless, the pipeline runs every step with Claude Code.

## Build status (2026-10-21 evening)
- Built: `python -m study convert | fix | mapnotes | lecture | site | check`, plus a site shell rendered from data
  (white, teal / amber / blue / red / green, no purple). The headless smoke test passes 4/4.
- Crypto: 7 PDFs converted. 48/63 flagged notes pages fixed (very good quality: exact LaTeX, figures
  described, the lecturer's typos flagged).
- **Cost finding:** on Claude Code (Sonnet), one 4-page fix batch uses about 3% of the 5-hour window, and that
  window is shared with my interactive Claude sessions. The automatic stop at 85% worked. → Bulk steps
  (1, 1b, 2, 9) must run on Google's quota (Gemini CLI or agy), with Claude for site visuals only.

## Round 5 (2026-10-21)
- **Colours, updated:** white can go, **light theme** (not dark), **Apple-style system colours** (soft, not
  primary colours), still **no purple**. → `site.css` now uses an off-white page and the accessible system
  teal / orange / blue / red / green; dark mode only when toggled.
- **Phone access:** each module gets its own repo with the site published on GitHub Pages; the README carries the
  github.io link. Crypto → `Renanlvrt/Cryptography`.
- **Split of work:** Antigravity (agy, Google quota) does the reading and teaching content (fix pages, map
  notes, capture, audit, registry, teaching, exercises, mocks). Claude Code does only the visuals, interactive
  sandboxes and videos. Don't spend Claude tokens on simple reading.
- **Headless agy:** use it the way `semi-automated-placement` does: `agy -p <PROMPT FILE PATH> --print-timeout Nm`.
- **Pages decision (asked 2026-10-21):** GitHub Pages from the private repo, **unlisted public URL** (noindex +
  robots.txt). Pages was accepted on the private repo. Live: https://renanlvrt.github.io/Cryptography/
- **Why headless agy used to hang:** it waited for the StitchMCP server, which never connected. With my OK,
  StitchMCP was disabled in `~/.gemini/antigravity-ide/mcp_config.json` and removed from
  `~/.gemini/config/mcp_config.json` (backups `*.bak-2026-10-21` next to both). If Stitch is missing in the
  IDE, this is why; restore the backup to get it back.
- Checked: Gemini Argon High page fixes match the Sonnet quality (exact LaTeX, figures transcribed, typos flagged),
  4 pages in about 2 min, with zero Claude tokens.
- **Round 6:** the published layout is "absolutely perfect". Wanted: the content, the interactive parts, all
  the animations **and short videos**; **buttons instead of plain links** (done: part picker, lecture tiles,
  today's actions). Videos: step 7c (`07c_videos.md`), 1–3 per lecture, 30–60 s, silent with captions,
  written by Claude, rendered locally with Manim 0.19 (free), shown under the concept.
- **Round 7 (2026-10-21 evening): "everything should be conducted by you (Claude)… way safer… way better
  results."** → Claude Code is the default runner for **every** step (Sonnet; audit on **Opus**). Everything
  Gemini produced was redone with Claude: 50 page fixes (un-marked and re-fixed from the images), the notes map,
  and Lecture 1's capture / audit / registry (archived in `data/study/archive/`). Antigravity stays as an opt-in
  fallback only. The page manifest now records `fixed_by` per page.
- **Round 8:** "it really should be flawless": animations, motion graphics and interactive modules really good,
  for **all hard concepts** I possibly don't know; **define all the words**; **draw tables, lots of drawings**,
  the best visual explanations; NotebookLM (cinematic) videos for niche topics; agents in parallel if faster.
  → Teaching gains `glossary` (every term: plain + formal), `intuition`, `tables`, `figures`,
  `extra_animations`, `difficulty`/`hard`; hard concepts get 2–3 animations, a table, a figure, a video.
  The stepper gets **magic move** (keyed shapes glide between frames) and `Study.figure` drawings; a Glossary tab.
  Visuals: 2 concepts per call with only their data. Exercises / visuals / videos / NotebookLM run **in
  parallel** after teaching (separate `claude -p` processes, not subagents of the chat).
  NotebookLM: step `nlm` via unofficial notebooklm-py; explainer format (cinematic needs AI Ultra), one
  video per hard concept (≤ 5 per lecture), sourced from the audited Master; needs `notebooklm login` once.
  `check` now requires glossary + figures everywhere and the full hard-concept kit.
- **Usage stop raised to 95%** (was 85%) on request; live-configurable in `data/study/limits.json`.

## Round 9 (2026-10-22): token budget
- "2 times the 5h limit per lecture will be way too much… 49 concepts can be across the 10 or 20 lectures…
  2 to 5 concepts with visuals and everything… for all 6 modules + 2 semesters a year… not too much for little
  content." → **Topic mode**: every concept stays in the notes, glossary and flashcards (cheap), but the rich
  teaching (animations, sandboxes, figures, videos, exercises) is per **topic, 2–5 per lecture**.
  - Audit: one Sonnet pass returning edits (Opus ×3 full rewrites cost ~23 % of a window).
  - Topics (3c) replaces the registry (3b): small call, part-level `topics.json`, `prior` new/extends/recap.
  - Teaching: one call (topics + lecture glossary + 2 cards per concept). Exercises: one call per lecture, per topic.
  - Visuals: per topic. Manim video: at most 1 per lecture. NotebookLM: at most 2 hard topics per lecture.
  - Lecture 1 (built before this change) keeps all its paid-for content: 49 concept designs, 248 exercises,
    8 Manim videos, 6 concept visuals; only its topics and the missing topic visuals are added.
- Bugs fixed: usage-limit errors inside the parallel steps now make the driver sleep instead of failing;
  NotebookLM login is checked with a real call (its cookies had expired although `auth check` said valid).
- **Round 10 (2026-10-22 morning):** finish all Crypto lectures by 10:00, at most **one 5-hour window per
  sub-module (part)**; "an explanation of all concepts but I don't need visuals and interactive things for all
  of them"; "Yes I want manim video, maybe one every few lectures that are really hard to understand".
  → Lean mode: lectures 4, 6, 7, 9–13, 16, 17 built from the notes chapters (`notes_lectures.json`), 5 in
    parallel; `concept_notes` explain every concept; visuals only for the hardest topic (2 for dense lectures);
    audit + topics on Haiku; exercises one call with smaller minimums; Manim films via
    `python -m study films <Module> <Part> --every 3` (hardest topic per group of 3 lectures).
