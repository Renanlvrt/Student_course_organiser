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
  - (Not chosen: self-marking by revealing a model answer and mark scheme.)
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
- My newer prompt (to merge into the pipeline prompts).
