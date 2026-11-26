# Recorded experiments and reproduction

This directory holds the research material for Study Desk Lite. Commands run from the
repository root. [Setup](../docs/SETUP.md) covers installation; the [pipeline
guide](../docs/PIPELINE.md) explains application behavior.

The [recorded project demo](https://Matt-C-Portfolio.github.io/study-desk-lite/) presents
this corpus and its saved results without installation. Its library and charts come from
the same bundled snapshot below; opening the site does not run models or make API calls.

## Dataset and configurations

- Ten curated MIT OpenCourseWare computing lectures, listed in [lecture-presets.json](../lecture-presets.json).
- Saved caption transcripts, held consistent across systems. Whisper is an optional
  app capability, not the transcript source for the recorded corpus comparison.
- Four systems: DeepSeek R1 Distill Qwen 1.5B, 7B, and 14B Q4_K_M, plus OpenAI.
- Guide comparison: five attempts per lecture/system (50 per system); local seeds
  42-46. The OpenAI repeats are unseeded; guide stages use Luna / Terra / Terra / Luna.
- Graph comparison: each system's first completed guide extraction per lecture;
  graph decisions use local seed 42. These are system-specific graphs, not identical
  graph inputs passed to different answer models.
- Q&A: 120 questions, four systems, four modes, one attempt per combination:
  1,920 attempts. Local seed 42; OpenAI unseeded.
- Q&A modes: `plain` (model only), `rag`, `graph_only`, and `graph` (RAG + graph).
- Up to six passages in retrieval modes; 3,000 output tokens. Equal passage counts
  do not imply equal input-token counts.
- OpenAI Q&A used up to seven concurrent workers. Local inference was sequential;
  API and local work could overlap. Timing includes possible shared CPU contention.

See [pipeline documentation](../docs/PIPELINE.md) for stage prompts, model assignments,
output budgets, checkpoint behavior, and graph candidate selection. The source modules
contain the exact prompts. Original failures remain part of the recorded results.

## Included results and summary tables

- [Attempt metrics](results/qa-attempts.csv), [summary tables](results/qa-summary.csv),
  and [export provenance](results/provenance.json).
- [Saved example guide](../baseline/notes.md) and [settings](../baseline/settings.json).

Rebuild the tables with Python's standard library; no database, model, or API is needed.
The commands use the setup environment, but any Python 3.11 executable works:

```powershell
.\.venv\Scripts\python.exe scripts/summarize_results.py
```

This reads `evaluation/results/qa-attempts.csv` and writes
`evaluation/results/qa-summary.csv`. It groups attempts by system/mode and by system
overall. The table includes completions, failures, failure percentage, median elapsed
time of completed attempts with recorded timing, and estimated API cost across attempts.
Missing API costs are counted explicitly. Local cost entries do not measure hardware or
electricity.

The CSV export includes all 1,920 terminal attempts. It excludes credentials, absolute
output paths, API request bodies, and generated answer text.
`evaluation/results/provenance.json` records the original manifest hash, pipeline
hashes, and experiment settings.

| System | Completed | Failed | Attempts |
| --- | ---: | ---: | ---: |
| 1.5B | 449 | 31 | 480 |
| 7B | 467 | 13 | 480 |
| 14B | 469 | 11 | 480 |
| OpenAI | 479 | 1 | 480 |

These tables describe execution reliability, timing, and cost, not answer accuracy. API
costs are historical estimates, not billing receipts.

## Included dataset

[`dataset/manifest.json`](dataset/manifest.json) describes the bundled snapshot and its
SHA-256 checksums. About **94 MB compressed** contains 35,307 original artifact files
(about 261 MB extracted) plus the database snapshot:

- All ten lecture URLs, metadata, attribution, thumbnails, and saved caption transcripts.
- All 205 saved guide attempts, including early attempts and failures; the comparison
  cohort remains the selected 200 attempts. Prompts, intermediate responses, final
  guides, timings, and per-run diagnostic logs are retained.
- Five graph build records, including the held build and four completed system graphs;
  graph artifacts, concepts, relationships, evidence, and saved embeddings.
- The transcript retrieval index for all ten lectures (251 passages).
- The complete 1,920-attempt Q&A experiment, generated answer text, requests/responses,
  timings, costs, manifests, graph snapshots, and other saved answer experiments.

The seven `artifacts-*.zip` files are ordinary, independently readable ZIP archives.
`database.json.gz` holds the application tables as compressed JSON, with portable file
references. No database password or API key is included. The snapshot omits only four
root server logs and six transient lock/temporary files, listed in the manifest.
Downloaded videos/audio, model weights, and inference binaries are not included.

After configuring PostgreSQL, load the snapshot once into an empty installation:

```powershell
.\.venv\Scripts\python.exe scripts/dataset.py restore
```

This populates the actual app library and makes the comparison's saved-answer links
work. It requires no inference or paid request and refuses existing files or records.
See [setup](../docs/SETUP.md#load-the-included-project) for the complete browsing path.

Artifact files are restored byte for byte. Only database file references are rebased;
historical JSON artifacts retain their original machine paths and provenance hashes.
The archives are the submitted snapshot; `data/` is its local working copy and remains
ignored by Git. Changes made in the app do not modify the bundled experiment.

Check bundle checksums without restoring, or export a separate snapshot after stopping
all processing jobs:

```powershell
.\.venv\Scripts\python.exe scripts/dataset.py verify
.\.venv\Scripts\python.exe scripts/dataset.py export --bundle ..\separate-dataset
```

Export reads the configured database and data directory without changing them. It
requires a new destination. Keep the recorded dataset when conducting new experiments.

## Fresh runs

To reproduce the workflow with fresh outputs, complete [setup](../docs/SETUP.md), save
the curated transcripts, generate guides, build each system's graph, and index the
selected transcripts. Save your transcript hashes and environment information; captions
fetched later can differ from the recorded corpus. Model versions, hardware, and runtime
behavior can also affect results.

The question bank has 30 questions in each of four categories and is a project
evaluation set, not an independently validated benchmark. Its reference materials remain
separate from the retrieval index. See the [question-bank
notes](question-bank-v1/README.txt) for category definitions, source hashes, and
attribution. All 30 Connections questions use multiple lectures.

To export metrics from the restored original manifest:

```powershell
.\.venv\Scripts\python.exe scripts/summarize_results.py --export-from data/experiments/qa-full-v1/manifest.json --output ..\exported-results
```

This writes a separate export without modifying the original manifest or launching
generation. Fresh experiments should use a separate output directory and be labeled
separately from the included results. Use `--output` with the table-only command as well
if you want to keep the included summary untouched.

## Historical runners

These scripts document the recorded batches. They are not imported by the app or needed
for summary tables. The guide and Q&A runners execute paid API work with their
prerequisites; inspect their source before running them. Use normal app controls for new
guide generation.

| Script | Purpose and required state |
| --- | --- |
| [guide-runs/openai_baseline.py](guide-runs/openai_baseline.py) | One four-pass API baseline. Requires server port 8788, lecture database ID 1 with a selected transcript and a saved 14B run supplying attribution, and `OPENAI_API_KEY` in the environment. Its inline adapter/pricing reflect the historical run. Entry point: `python evaluation/guide-runs/openai_baseline.py`. |
| [guide-runs/run_openai_repeats.py](guide-runs/run_openai_repeats.py) | Forty additional API guide attempts, up to seven workers. Requires the original `data/experiments/openai-repeat-progress.json`, matching lecture IDs, transcript paths/hashes, run numbering, database, and server. The progress file is archived in the dataset for reference; its historical paths are not rewritten. It cannot initialize a fresh cohort. |
| [qa-full-v1/run.py](qa-full-v1/run.py) | Windows-specific full Q&A batch at port 8788 using default `data/`. Queues all four systems, checks pipeline hashes, preserves terminal failures, and writes the manifest and graph snapshots. Executes work at module level; do not import it or invoke it for help. |
| [qa-full-v1/comparison_snapshot.py](qa-full-v1/comparison_snapshot.py) | Publishes saved Q&A metadata to `study_desk/web/data/answer-comparison-data.json`; answer files stay in place. |
| [question-bank-v1/build_bank.py](question-bank-v1/build_bank.py) | Authored question bank and offline renderer. Reads saved database sources and writes bank files; performs no inference. |

Source organization has changed since the recorded experiments. Original provenance
hashes are preserved: do not resume an old manifest against changed pipeline files,
bypass its hash guard, or overwrite original experiment folders. Current API behavior
lives in `study_desk/openai_model.py` and `study_desk/study_jobs.py`.
