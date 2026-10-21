# Alt+O Download Organiser — Final Spec (agreed 2026-10-21)

Base: the original PRD, with the decisions below overriding it.

## Root & structure
ROOT = `C:\Users\renan\Desktop\Durham2\courses` (set in config.json, not hardcoded).

Module folders (short names):

| Folder       | Code     | Full name                                       | Parts (folder names)                                        |
|--------------|----------|-------------------------------------------------|-------------------------------------------------------------|
| AADS         | COMP3811 | Advanced Algorithms & Data Structures           | Design of Algorithms and Data Structures / Advanced Algorithms |
| Crypto       | COMP3731 | Cryptography                                    | Symmetric Cryptography / Asymmetric Cryptography            |
| DLCV         | COMP3801 | Deep Learning & Computer Vision                 | Deep Learning / Computer Vision                             |
| RL_AGT       | COMP3821 | Reinforcement Learning & Algorithmic Game Theory | Algorithmic Game Theory / Reinforcement Learning           |
| AppliedSec   | COMP3761 | Applied Security                                | Term 1 / Term 2                                             |
| ProjectPrep  | COMP3591 | Project Preparation                             | Term 1 / Term 2                                             |
| _Unsorted    |          |                                                 |                                                             |

Part folders use the part name only (no "Part N" prefix).

Layout per module (lectures first): `Lectures/<Part>/Lecture NN - Topic/`, `Practicals/<Part>/Practical NN - Topic/`, `Website/<Part>/` (one site per submodule, for future integrations), and `Other/`. Answers go inside their practical (or lecture, if they say "lecture"), readings inside their lecture. Coursework briefs, past papers, handbook and anything not tied to a number go in `Other/`.
Module-wide items (assessment briefs, exam papers, handbook) go at module level in
`Assessment, Exam Prep, Other` next to the part folders.
The full empty skeleton is created on first run.

## Naming
- One folder per lecture: `Lectures\Lecture 03 - Topic\` holds the slides, the notes chapter, etc., each named `Lecture 03 - <own topic>.pdf`.
- `Practical NN - ...` and `Solutions NN - ...` follow the same naming pattern.
- If the number is unknown, use the next free number in that folder.
- Practicals: one subfolder per practical, `Practicals\Practical 01 - Topic\`, holding the sheet (renamed) plus its code/notebook files (original names kept).
- Solutions go in `Solutions\Solutions NN - Topic.ext`.
- Never delete or overwrite. On a name clash, append ` (2)`.

## Files handled
PDF, PPTX, DOCX, .py, .ipynb, .c, .zip, .txt, .md, .csv. Everything else stays in Downloads.
Ignore .crdownload/.tmp/.part/~$ files and files still being written.
Zips: moved and auto-extracted next to the zip; the zip is kept.
Duplicates (identical content hash to an already-sorted file): not moved, left in Downloads, and the dashboard shows "already have it".

## Classification
1. Blackboard context from the extension, if present (course code + section), is the most trusted and **wins over the dashboard pick**.
2. Dashboard pick (module, optional part).
3. Rules: COMP codes, filename patterns (lecture/week/practical/answers/solutions), part keywords.
4. Gemini Flash fallback for anything unresolved (module/part/category/number/topic). Key comes from the `GEMINI_API_KEY` user env var only.
If module = chosen and part = Auto, the AI/rules detect the part from content.
Low confidence or failure: move to `_Unsorted`, highlighted row in the dashboard with the best guess and one-click buttons (Accept guess / module buttons) plus drag and drop.

## Activation & UI
- Global Alt+O toggles Off ⇄ Active.
- Active: a small always-on-top dashboard appears **bottom-right** (draggable, position remembered). It is kept minimal: On/Off dot, an `Auto ▾` module menu, and a list with one line for the name and one muted line for the destination. Files to check show `✓ guess` / `Move`, sorted ones reveal `move · undo` on hover. Drop targets appear only while dragging.
- Extension downloads are always sorted, even when Alt+O is off. The popup lists where each file went.
- Off: stops watching and hides the dashboard. History is kept in the log and can be reopened from the tray ("Open dashboard"). A toast shows "Organiser ON: X" / "OFF".
- Per-item Undo moves the file back to Downloads under its original name.
- "Sort existing" button: sorts files already in Downloads via preview + approve.
- Tray icon: Open dashboard, Open courses folder, Open log, Reorganise existing, Quit.
- Starts with Windows via a Startup shortcut (pythonw, no .exe).

## Chrome extension (Manifest V3, unpacked)
- On Durham Blackboard Ultra: reads the course code and section/folder name, and tags each download with them (sent to the app on localhost).
- "Download all new files in this section" button: expands folders and downloads gently one at a time, skipping files already downloaded. Only runs when you click it.

## One-off migration
"Reorganise existing" shows a preview of planned moves for the current `courses\Applied_Security`, `DL`, `Project Prep` and runs only after approval. Folders like the VM/repo are moved whole.

## Implementation notes (decided during build)
- Gemini model: `gemini-3.5-flash`, falling back to `gemini-flash-lite-latest`. `gemini-2.5-flash` is closed to new API keys. Both are set in config.json.
- Alt+O uses Win32 `RegisterHotKey`, which needs no keyboard hook and works over admin windows. The keyboard library is only a fallback.
- The extension reads course code and folder path from Blackboard's REST API using your logged-in session, with DOM clicks as a fallback. "Download all" lives in the extension popup.

## Security
- `.gitignore` was created first. No secrets in code, config or the repo.
