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

To sort old files or folders, use **⋯ menu → Sort files already in Downloads… / Reorganise old course folders…**.
Both show a preview first, and nothing moves until you click Apply.

## Chrome extension (one-time)
1. Go to `chrome://extensions` and turn on **Developer mode** (top right).
2. Click **Load unpacked** and pick `extension\` in this folder.
3. Reload any open Blackboard tab.

From then on, every Blackboard download is tagged with its course code and folder, so sorting is exact.
On a course page, click the extension icon, tick sections, **Scan**, then **Download N new files**.
Files download one at a time, and files you already have are skipped.

## Setup / maintenance
- Install the dependencies with `python -m pip install -r requirements.txt`.
- The AI key goes in the Windows user environment variable `GEMINI_API_KEY`. It is never stored in files.
- Run `powershell -File scripts\install_startup.ps1` to start at login (or `uninstall_startup.ps1` to stop).
- Run it by hand with `pythonw run.pyw`, or `python run.pyw` to see logs in the console.
- Settings live in `config.json`: folders, hotkey, modules, keywords, confidence threshold and Gemini model.
  Next year, edit the `modules` list there.
- Logs and history are in `data\` (gitignored): `log.json` holds every move, `organiser.log` holds errors.
- Tests: `python -m unittest tests.test_rules` (offline) and `python -m tests.acceptance` (end-to-end in a temporary folder).
