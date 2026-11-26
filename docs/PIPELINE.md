# Pipeline and architecture

These describe the recorded implementation. File names in the responsibility table are
relative to `study_desk/` unless stated otherwise. For installation, see
[SETUP.md](SETUP.md).

## Study guides

Selected transcript -> Extract -> Consolidate -> Review -> Format -> saved guide.
Current versions are `study-desk-local-v9`, consolidation `grouped-v3`, and formatting
`format-rules-v5`. See [recorded experiments](../evaluation/README.md) for the dataset,
seeds, and system comparison settings.

Formatting uses content-free rules for paragraphs, bullets, steps, comparisons,
formulas, and code. No reference lecture excerpts are supplied. Each run saves the exact
formatting prompt, hash, and version. Earlier example-based outputs retain their
original settings. The saved baseline is a sample output, not a prompt input.

The five-seed queue runs sequentially; failures count as attempts and the queue
continues. Each call uses its run's seed. A server restart marks unfinished/queued runs
interrupted without retrying. Seeds improve repeatability on the same setup, not
bit-for-bit reproducibility across hardware and runtimes.

All three models use the same transcript preparation, prompts, JSON schemas, 32K context
and temperature (0.6). Output budgets are 6,000 tokens for extraction, 16,000 for
consolidation, 3,000 for review, and 12,000 per presentation topic. Formatting bounds
titles to 90 characters, bodies to 1,400, captions and LaTeX to 500, and list items to
700. Each topic produces one section. Formatting has its own checkpoint revision so
fixes can reuse earlier extraction and review. The local tokenizer measures the chat
prompt; output is capped to remaining context with a 512-token reserve. Evidence is
never silently truncated. Each call saves its budget. Each generation creates a fresh
numbered run per lecture and model. Step 3 lists all attempts, including failures, with
per-run notes and comparison results. The first completed run per lecture/model is
selected for the graph; later runs do not replace that selection. Existing saved results
are imported as Run 1.

Each model has separate results. Original responses, review observations, output issues,
and timings remain available for comparison. Review observations are advisory and never
filter formatting input.

`lecture_contracts.py` owns the teaching prompts and schemas. Extraction has no
concept-count cap. Consolidation groups extracted topics by ID; local code preserves
their original explanations, details, and examples when assembling the groups.
Formatting processes one topic per call, with individual checkpoints and topic-based
progress. All organized content goes to formatting. Study notes contain the model's
notes and lecture references; review observations stay in Comparison results. Only basic
structure and reference checks are enforced so the app can read outputs.

Pass timings exclude model loading. Total time includes loading and cleanup. Resumed
passes label reused calls; cached runs are not fresh speed benchmarks. Each new attempt
keeps a timing file. Changing pipeline version or transcript starts a new result folder.

## Files and responsibilities

| File | Responsibility |
| --- | --- |
| `cli.py` | Start the UI or transcribe a local file |
| `intake.py` | Validate YouTube URLs |
| `video.py` | Fetch metadata, captions, thumbnails, and audio |
| `transcription.py` | Run local Faster-Whisper |
| `processing.py` | Coordinate one background job at a time |
| `study_pipeline.py` | Prepare source chunks and run four passes |
| `study_jobs.py` | Save generation progress and timings |
| `study_runtime.py` | Start the selected model and unload it afterward |
| `model.py` | Token budgeting and streamed local model requests |
| `lecture_contracts.py` | Local teaching prompts, schemas, and stage budgets |
| `lecture_document.py` | Typed sections, steps, callouts, code, and Markdown rendering |
| `storage.py` / `schema.sql` | PostgreSQL records and table definitions |
| `ui.py` | Local HTTP routes |
| `openai_model.py` | API model adapter and recorded stage assignments |
| `retrieval.py` | Transcript indexing and BGE search |
| `answer_graph.py`, `answers.py` | Graph retrieval and saved Q&A jobs |
| `web/` | HTML, CSS, JavaScript, and vendored browser assets |
| `web/data/` | Fixed guide-comparison cohort and recorded Q&A comparison JSON |

The notes viewer renders Markdown with vendored Marked and DOMPurify. Saved model text
stays unchanged, raw pass outputs display as plain text, and guide formulas show LaTeX
source. Q&A uses bundled KaTeX and clickable evidence previews.

PostgreSQL stores lecture metadata, transcript selection, and model-run history.
`data/videos/<id>/` stores metadata JSON, thumbnail, audio, and transcript files.
`data/videos/<id>/study/<model>/run-<number>/<source-hash>/` stores pass outputs and
timings.

## Concept graphs

The Lecture graph tab builds one graph for each of 1.5B, 7B, 14B and OpenAI across the
ten curated lectures. Each build snapshots the **first completed run** for each
lecture/system, reading `extract-N.json` and `source.json`, not the formatted guide.
Original statements, examples, source chunks and content hashes are retained. Bullet
positions supply stable claim IDs; a topic with no bullets retains its gist as a labeled
gist record.

Code seeds concept candidates directly from each extracted topic, attaching its existing
claims and evidence without an assignment model call. Topic identity uses lecture and
extraction position, not title equality. BGE proposes two nearest neighbors per starting
topic for equivalence review; only the model can merge them. After consolidation, it
proposes three neighbors per surviving concept for relationship review. Model calls
process up to 20 fixed answer slots: merge/keep pairs, broad subject-area names, or
directed relationship/none pairs. Code owns IDs and attaches supplied evidence context.
All original statements and examples remain attached through merges. This reduces calls
without asking the model to classify every claim again.

The same topic-based pipeline applies to all three local models, using seed 42 and the
existing Q4 runtime. OpenAI graph generation starts only through its own Build graph
button; its stages are Terra / Terra / Luna. Build all local graphs excludes OpenAI.
Background reservations respect existing holds; a direct OpenAI build action can start a
fresh build without resuming an old held worker. Keys remain outside the repo.

PostgreSQL stores graph inputs, unchanged claims, shared evidence-span vectors,
concepts, memberships, aliases, merge decisions and edges. Relationship links retain the
original claims supplied as context and their source passages; these are evidence
context, not a claim that every supplied passage proves the edge. Model
omissions/invalid answers remain visible as issues; unassigned claims are retained.
Source subpassages retain the enclosing extraction chunk's timestamps rather than
invented finer timestamps. Concept vectors encode name and description; long embedding
inputs are windowed and normalized, not truncated.

`graph.py` selects and prepares sources; `graph_contracts.py` defines model tasks;
`graph_pipeline.py` executes them; `graph_store.py` persists them; `graph_jobs.py` owns
progress and inference. Only one processing job runs at a time. Each batch checkpoints
graph records, and raw requests/responses are saved in `data/graphs/build-NNNN`. A
restart marks unfinished builds interrupted; a new build preserves earlier builds.
Repeating the initial build request reuses the same input fingerprint. The explicit
new-version button starts a separate build.

Selecting a concept shows its claims, topic examples, source text, timestamps and
model-proposed relationships. Search and subject-area filters narrow the view. Q&A
retrieval modes are described below.

### Transcript retrieval

Transcript indexing uses the selected saved transcript for every video; see [setup
commands](SETUP.md#6-check-and-launch). It reuses cached BGE-base-en-v1.5 passage
embeddings from graph preparation. PostgreSQL stores the selected transcript fingerprint
and passage membership in `rag_transcript` and `rag_passage`; original graph evidence is
preserved. Removing a video cascades to its retrieval index.

Retrieval uses the BGE query prefix and cosine similarity across all indexed videos. At
this dataset size, a NumPy dot product over PostgreSQL's stored vectors is sufficient;
no separate vector service is needed. Results contain passage text, score, video ID,
attribution and source links. Timestamps cover the original transcript chunk, not an
exact sentence. Re-index after changing a transcript selection; search rejects stale
indexed selections. No model answers or question-bank material are indexed.

### Ask Study Desk

Ask Study Desk appears beneath Video library. Select a local model or OpenAI Luna and
one of four modes: model only (no sources), RAG (six BGE-ranked transcript passages),
graph only (concept-linked evidence expanded through relationships, without
full-transcript search), or RAG + graph (three direct passages plus up to three one-hop
graph neighbors, ranked with BGE; direct results fill unused slots). Graph expansion
uses that system's latest completed graph and checks its evidence against the transcript
index.

Answers are separate saved jobs under `data/answers/<id>/`, including the question,
prompt, original response, selected sources, graph build, seed, timing and API
usage/cost when applicable. Local seeds default to 42; OpenAI is unseeded. All modes use
a 3,000-token output cap. Citation warnings preserve missing/invalid citations instead
of rewriting model output. Jobs share the existing processing lock and release local
model memory afterward. The interface restores the most recently viewed answer after
refresh. No question-bank answers are supplied to the model.

Graph modes use `answer-explanations-v7-budget6`; model-only and RAG use
`answer-explanations-v5-latex`. For retrieved answers, the model returns Markdown blocks
plus source IDs constrained to the supplied passages. Blocks can contain prose, lists,
code, or formulas. All models and answer modes share tutor-style instructions for
developed explanations, natural headings, paragraphs, lists, code, and formulas. Short
factual questions can still receive short answers. The app renders these as clickable
citations. An evidence-limitation field allows unsupported questions to remain
unanswered without invented attribution. Raw output and block mappings are saved.
Earlier answers retain their original format.

Cited sources are listed separately from other retrieved passages. Saved answers render
as stored.
