# Alt+O Download Organiser

Sorts course downloads into `Durham2\courses\<Module>\{Lectures,Practicals,Website}\<Part>\` (+ `Other\`) and renames them
(`Lecture 03 - Topic.pdf`, `Practical 02 - Topic\`, `Solutions 01 - Topic.pdf`).
Full decisions: [SPEC.md](SPEC.md).

## Daily use
1. **Alt+O** turns it on (or click the dot in the dashboard). Pick a module from **Auto ▾** if you want; Auto lets the AI decide.
2. Download as usual. Each file appears with its new name and, underneath, where it went. Click the name to open its folder.
   - Amber dot "Where does it go?": click **✓ guess** to accept it, or **Move** to choose the module, part, type and name yourself.
   - Hover over a sorted file to see **move · undo**. You can also drag a row; module and type targets appear while you drag.
3. Downloads started from the Chrome extension are sorted even when Alt+O is off. When a batch finishes, a **recap** tab opens with a tree of where each file went. Drag a file onto another folder to move it, or hover and click **move** / **undo**.

**Duplicates** (byte-for-byte identical files): if you already have the file in the right place (or the folder
next to it), the extra download is removed. If your only copy is somewhere else (old folders, wrong module,
`_Unsorted`), the file is sorted into the right place and the stray copy is removed. You always end up with exactly
one copy, in the right folder. No Bin folder.

**Notebooks:** Colab/GitHub links are resolved to the real `.ipynb`. Notebooks linked inside slides and practical
PDFs are downloaded too. Every notebook gets a printable PDF copy next to it. Code linked from a lecture goes to the
practical on the same topic if there is one, otherwise it stays with the lecture.

**Failed downloads** are retried twice in the browser, then by the organiser itself. If they still fail, they
show in red (dashboard, popup and recap) with the reason and a Retry button.

To sort old files or folders, use **⋯ menu → Sort files already in Downloads… / Reorganise old course folders…**.
Both show a preview first, and nothing moves until you click Apply.

## Chrome extension (one-time)
1. Go to `chrome://extensions` and turn on **Developer mode** (top right).
2. Click **Load unpacked** and pick `extension\` in this folder.
3. Reload any open Blackboard tab.

From then on, every Blackboard download is tagged with its course code and folder, so sorting is exact.
On a course page, click the extension icon, tick sections, **Scan**, then **Download N new files**.
Files download one at a time, and files you already have are skipped.

## Always on
- The organiser starts at every Windows login (Startup shortcut, `scripts\install_startup.ps1`) and lives in the tray.
- If it isn't running when you use the extension (it crashed, or you quit it), the extension starts it
  automatically through a small native launcher (`scripts\install_native_host.ps1`, already installed). This
  happens when Chrome starts, when you open the popup, before every download is sorted and before retries.
- The extension has a fixed ID (`extension\EXTENSION_ID.txt`) so the launcher keeps trusting it.

## Setup / maintenance
- Install the dependencies with `python -m pip install -r requirements.txt`.
- The AI key goes in the Windows user environment variable `GEMINI_API_KEY`. It is never stored in files.
- Run `powershell -File scripts\install_startup.ps1` to start at login (or `uninstall_startup.ps1` to stop).
- Run it by hand with `pythonw run.pyw`, or `python run.pyw` to see logs in the console.
- Settings live in `config.json`: folders, hotkey, modules, keywords, confidence threshold and Gemini model.
  Next year, edit the `modules` list there.
- Logs and history are in `data\` (gitignored): `log.json` holds every move, `organiser.log` holds errors.
- Tests: `python -m unittest tests.test_rules` (offline) and `python -m tests.acceptance` (end-to-end in a temporary folder).
