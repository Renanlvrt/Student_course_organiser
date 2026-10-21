# Step 1: Repair badly extracted pages

**Runner:** any vision model. **Unit:** a few flagged pages of one PDF.

A local tool converted `{{PDF_NAME}}` to markdown, but these pages were flagged as poorly parsed (page:
reason): {{FLAGGED_PAGES}}

For **each page listed below**:
1. Open the page image with the Read tool (the path is given). It is the ground truth.
2. Compare it with the current markdown for that page, also given below.
3. Write a **complete, faithful** markdown version of the page:
   - **Maths:** exact LaTeX in `$…$` / `$$…$$`, including sub/superscripts, indices, operators (⊕, ∥, mod,
     Pr[·], ∑, fractions) and any alignment that carries meaning. Keep the source's notation, and its typos
     too (add `> ⚠ Check:` next to a likely typo).
   - **Diagrams / figures:** a `> 🖼 Figure:` block describing it so someone could redraw it. Include every
     box, arrow, label, value and what the figure shows. For a circuit or construction (LFSR, Feistel round,
     CBC chain, …) list the components and connections in order.
   - **Tables:** markdown tables with every cell. Two-column layouts: read each column top to bottom.
   - **Code / pseudocode:** fenced blocks, verbatim. Headings use `##` for a slide or section title.
   - Keep every word that the current markdown already has right. Drop nothing, including footnotes and
     page numbers.

{{PAGES}}

## Output
Reply with **only** one fenced ```json block that maps each page number to its new markdown:
```json
{"5": "## LFSR Mathematical Definition\n\n...", "6": "..."}
```
If a page image is unreadable, set its value to `"NEEDS HUMAN: <why>"`.
