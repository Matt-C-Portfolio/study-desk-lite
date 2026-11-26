STUDY DESK LITE — QUESTION BANK v1

120 questions: 3 per category per lecture, across the 10 curated MIT lectures.
Categories: Lecture details, Understanding, Application, Connections.
All 30 Connections questions use at least two lectures.

FILES
questions.html: readable/printable question sheet, with no answers.
questions.json: the 120 questions used in the recorded Q&A experiment.
answer-key.html: questions, answer checklists, evidence and notes for the evaluator.
answer-key.json: evaluator checklists and evidence IDs.
sources.json: attribution, exact saved-caption evidence, source paths and SHA-256 hashes.
build_bank.py: source for the authored set and offline renderer; reads the database only.
validation.json: structural and arithmetic checks performed on this set.

USE
The recorded experiment used model-only, RAG, graph-only, and RAG + graph modes.
Do not supply the answer key, evidence excerpts or evaluator notes to the answering model,
and do not add this folder to the retrieval index. Retrieval should use the lecture corpus.
Use the same question wording and comparable answering settings for all modes.
Lecture-specific questions identify their context in the wording; no lecture UI selection is needed.
The primary lecture groups questions for reporting; it does not restrict retrieval.
Use the checklist as required content, not an exact-string answer. Accept equivalent explanations.
For application questions, check the computation as well as the explanation.
For Connections questions, look for both sides of the comparison and an explicit relationship.
Judge factual correctness separately from whether available-source citations support the answer.
A model without retrieval should not fabricate transcript citations.

SCOPE
This is a draft evaluation bank, not an independently expert-validated benchmark.
Questions were based on saved manual-caption transcripts, not model-generated guides.
Application values/scenarios are new; their underlying methods come from the cited passages.
Connection questions test synthesis but do not assume the graph will outperform RAG.
Some questions can be answered from general knowledge; lecture details also test source-specific recall.
The set does not separately test unanswerable questions or refusal behavior.
Historical Python division is explicitly scoped to the 2008 lecture’s Python 2 behavior.
Caption formula slips are retained in evidence, not silently rewritten as source text.
No slides, hidden diagrams, external pages or guide outputs were used as the answer key.
The bank builder itself performs no inference. The separate Q&A runner later used
these questions for 1,920 recorded attempts; see ../README.md.

ATTRIBUTION
MIT OpenCourseWare. 6.00: Eric Grimson and John Guttag. 6.034: Patrick Henry Winston.
Lecture links, titles and saved license records are in sources.json and both HTML files.
Adaptations: original questions, worked scenarios, paraphrased checklists and cross-lecture comparisons.
CC BY-NC-SA 4.0: https://creativecommons.org/licenses/by-nc-sa/4.0/
