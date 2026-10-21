# Step 7c: Short videos for one lecture (Manim)

**Runner:** Claude Code. **Unit:** ONE lecture. The pipeline renders your file locally with Manim Community
v0.19 (`manim -qm`, 1280×720, 30 fps) and embeds each video under its concept on the site.

For every concept whose teaching data has a `video` storyboard, write **one `Scene` class** that films that
storyboard, shot by shot, in order. Each video is **30–60 seconds**, silent, with captions on screen.

## Style (match the site)
- `config.background_color = "#fbfbfd"`. Text and lines in ink `#1d1d1f`, secondary `#6e6e73`.
- One meaning per colour, as on the site: plaintext/inputs `#0a6fd6`, keys/secrets `#c26a00`,
  ciphertext/outputs/wrong `#d93a32`, correct `#248a3d`, structure/highlights `#0a84a0`. **No purple.**
- Captions: one short sentence per shot, `Text(..., font_size=28)` at the bottom edge (`to_edge(DOWN)`),
  faded out before the next one. Maths with `MathTex` (LaTeX is installed). Keep everything inside the frame.
- Calm pacing: each shot `self.play(...)` with `run_time` 1–2 s, then `self.wait(1.5–3)` so the caption can be read.
- Show what changes: move, transform and highlight the part that matters and keep the rest still.

## Rules
- Faithful to the master notes and the course's notation. Anything not in the notes is not stated as course content.
- Numbers on screen must be correct: compute them in Python inside the scene (real XOR, real modular arithmetic).
- Use only `from manim import *` and the Python standard library. No images, sounds or external files.
- Class names: `V_` + the concept id with every non-alphanumeric character replaced by `_`
  (e.g. `L03.lfsr` → `V_L03_lfsr`).

## Output
The complete file between `<<<MANIM_PY` and `MANIM_PY>>>`, then a JSON list between `<<<VIDEOS` and
`VIDEOS>>>`: `[{"class": "V_L03_lfsr", "concept": "L03.lfsr", "title": "..."}]`.

## Teaching design (the storyboards are in each concept's `video`)
{{TEACHING}}

## Master notes
{{MASTER}}
