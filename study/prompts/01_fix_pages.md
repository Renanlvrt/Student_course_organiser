# Step 1: Repair badly extracted pages

**Runner:** any vision model (default: Antigravity, Gemini Argon). **Unit:** one PDF, only its flagged pages.

A local tool already converted `{{PDF_PATH}}` to `{{MD_PATH}}`. These pages were flagged as poorly parsed,
each with the reason: {{FLAGGED_PAGES}} (e.g. `4: maths glyphs`, `9: large figure`, `12: table`).

For **each flagged page only**:
1. Open the PDF page image (`{{PAGE_IMAGE_DIR}}/page-NNN.png`) and read the current markdown between
   `<!-- page N -->` and the next marker.
2. Rewrite that page's markdown so it is a **complete, faithful** copy of the page:
   - **Maths:** exact LaTeX, including subscripts, indices, operators (⊕, ∥, mod, Pr[·]), and any
     alignment that carries meaning.
   - **Diagrams / figures:** a `> 🖼 Figure:` block describing it so someone could redraw it. Include every
     box, arrow, label, value and what the figure shows. For a circuit or construction (LFSR, Feistel round, CBC
     chain, …) list the components and connections in order.
   - **Tables:** markdown tables with every cell.
   - **Code / pseudocode:** fenced code blocks, verbatim.
   - Keep any text that was already correct.
3. Replace only that page's section in `{{MD_PATH}}`. Keep the `<!-- page N -->` marker.

Finish by printing: `page N: fixed (what changed)` for each page, or `page N: needs human (why)`.
