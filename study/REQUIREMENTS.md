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

## Open questions (answered below as we go)
<!-- filled in after the Q&A -->
