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

## Save a whole page (Alt+Shift+L)
On any web page, press **Alt+Shift+L**. The extension scrolls through lazy-loaded images, then saves the whole page
(including parts below the fold and embedded frames) as **one `.html` file** with its images, styles and fonts inside.
A Save As dialog lets you pick the folder and name. The file opens offline in any browser, and its text stays
selectable and searchable. The icon shows `…` while saving, `✓` when done and `!` (hover for the reason) if the
page can't be saved (Chrome's own pages and the Web Store are off-limits to extensions).
Pages that only render the rows you can see (e.g. long SharePoint lists) are saved as currently shown.
If the shortcut doesn't work, set it at `chrome://extensions/shortcuts`.
Saving uses the SingleFile library (AGPL-3.0, `extension/vendor/singlefile/`).
Test: `python -m tests.capture_smoke` (headless Chromium via Playwright, local test pages only).

## Copy a region (Alt+L)
Press **Alt+L** on any web page or PDF, then **drag a box** (or **click** a block on a web page, or a whole page in
a PDF). It is copied at once; paste it anywhere with **Ctrl+V** (OneNote, Word, chat…). Esc or right-click cancels.

**Several boxes:** hold **Shift** while you drag (or click) to keep a box and add another; kept boxes stay outlined
in green and numbered, and you can scroll between them. Release without Shift (or press **Enter**) to copy them all
together, in page order. **Backspace** removes the last box.
- **Editable text** (default, key **T**): the real text with its formatting (headings, bold, colours, lists, tables)
  so you can highlight and edit it; pictures, diagrams and formulas inside the box come along as exact screen crops.
  It also puts plain text on the clipboard for apps that only take text.
- **Exact image** (key **I**): the box exactly as it looks on screen, at the same size as Win+Shift+S (several boxes
  are stacked into one picture).
The last mode is remembered (separately for web pages and PDFs).

**PDFs** open in a built-in reader (PDF.js, the reader Firefox uses) instead of Chrome's, because Chrome's viewer
can't be read by extensions. There, Alt+L redraws the box straight from the PDF, takes the text from the PDF itself,
and the **Save…** button in the confirmation saves a **cropped vector PDF** of just the box (one page per box; sharp
at any zoom, with selectable text). Blackboard downloads (sent as attachments) still download and get sorted as before. PDFs from your
own computer open in the reader once **Allow access to file URLs** is on for the extension in `chrome://extensions`.
To keep Chrome's own viewer, right-click the extension icon and untick **Open PDFs in the built-in reader**.
Libraries: PDF.js (Apache-2.0, `extension/vendor/pdfjs/`), pdf-lib (MIT, `extension/vendor/pdf-lib/`).
Test: `python -m tests.clip_smoke`.

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
- **Automation Status**: Ctrl+Alt+O, the Desktop shortcut, Start menu ("Automation"), the tray menu or the dashboard ⋯ menu.
- Run it by hand with `pythonw run.pyw`, or `python run.pyw` to see logs in the console.
- Settings live in `config.json`: folders, hotkey, modules, keywords, confidence threshold and Gemini model.
  Next year, edit the `modules` list there.
- Logs and history are in `data\` (gitignored): `log.json` holds every move, `organiser.log` holds errors.
- Tests: `python -m unittest tests.test_rules` (offline) and `python -m tests.acceptance` (end-to-end in a temporary folder).
