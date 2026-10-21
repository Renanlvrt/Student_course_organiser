# Step 8: Exam profile and mock exams (once per part, after all lectures)

**Runner:** Claude Sonnet. **Inputs:** past papers, mocks and sample exams, with their answers if present:
{{EXAM_MD_FILES}}. Also every lecture's `concepts.json` and `exercises.json` for the part. Not examined:
{{NOT_EXAMINED}}.

## A: Exam profile → `{{OUT_DIR}}/exam-profile.md`
Analyse every past question:
- Its format and command words, marks and time per mark.
- Which concepts it tests and at what Bloom level.
- What the model answers include that earns the marks.

Build a **coverage matrix** of concept × past papers to show what was examined and what never was. Then
write a short "how to score on this exam" guide: time plan, answer structure, what markers reward and
recurring traps.

## B: Mock exams → `{{OUT_DIR}}/mocks/mock-NN.json` (default {{N_MOCKS}} = 5)
- Each mock matches the real exam's length, mark total, format mix and timing.
- **Generalise, don't overfit.** Across all mocks, every examinable concept appears at least once. At least
  40% of the marks in each mock test concepts or angles that **no past paper has asked**. Question styles
  vary beyond the past papers' templates while keeping the exam's command words and difficulty.
- No question may duplicate a past paper question or an exercise already in the bank.
- Each question has a full model answer, a mark scheme per point and the concepts tested. Auto-checkable
  parts get a `check` (same schema as the exercises).
- The website's **Mock exams** tab runs them with a timer, then marks the auto-checkable parts and gives
  AskClaude prompts for the rest.

Print the coverage matrix of concepts across mocks and the % of new-angle marks per mock.
