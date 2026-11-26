# Study Desk Lite

A local lecture-study application for the DATA 785 deep learning project.
It turns permitted YouTube lectures into study guides, connects concepts across
lectures, and answers questions using saved transcript evidence.

The project compares DeepSeek R1 Distill Qwen **1.5B, 7B, and 14B** (Q4_K_M)
with an optional OpenAI pipeline across ten MIT OpenCourseWare computing lectures.

**Browse without setup:** [Open the recorded project demo](https://Matt-C-Portfolio.github.io/study-desk-lite/).
The GitHub Pages version includes the lecture library, saved guides, concept graphs,
and full answer comparisons. It displays recorded results; new generation uses the local app.

[View the populated lecture library](docs/images/library.png).
The saved ten-lecture corpus and experiment outputs are included. Restore the bundled
dataset during setup to open the populated library, guides, graphs, and answer comparisons.

## Capabilities

- Save lecture metadata, captions, and optional local Whisper transcripts.
- Generate guides through Extract -> Consolidate -> Review -> Format.
- Build concept graphs from saved extractions and transcript evidence.
- Compare model-only, RAG, graph-only, and RAG + graph answers.
- Retain attempts, intermediate outputs, timings, and source references.

## Start here

- **Run the app:** [Installation and first run](docs/SETUP.md), including downloads,
  configuration, tests, troubleshooting, and submission packaging.
- **Understand the code:** [Pipeline and architecture](docs/PIPELINE.md).
- **Explore the project:** [Recorded experiments and results](evaluation/README.md),
  including the dataset, comparison settings, and reproduction instructions.
- **Read an example:** [Saved study guide](baseline/notes.md) and its
  [settings](baseline/settings.json); no installation needed.
- **Inspect the numbers:** [Q&A summary](evaluation/results/qa-summary.csv),
  [attempt metrics](evaluation/results/qa-attempts.csv), and
  [provenance](evaluation/results/provenance.json).

The tested local setup is Windows x64, Python 3.11, PostgreSQL 17, and an NVIDIA
GPU. The portable dataset is about **94 MB compressed** and includes the database
records needed to preload the app. Browsing saved results needs no model download or
API key. Model weights and inference binaries are separate downloads for generating
new results. Local inference needs no paid API; YouTube acquisition needs internet.
The optional OpenAI route sends source text to the API and incurs charges.

## Repository layout

| Path | Purpose |
| --- | --- |
| `study_desk/` | Application, SQL schemas, and browser assets |
| `tests/` | Unit and PostgreSQL integration tests |
| `scripts/` | Setup checks, dataset restore/export, metric tables, and packaging |
| `.github/workflows/pages.yml` | Builds and publishes the recorded demo from the bundled dataset |
| `docs/` | Installation and architecture |
| `evaluation/` | Research guide, bundled dataset, historical runners, question bank, and results |
| `baseline/` | Saved example guide, settings, and attribution |
| `models/`, `runtime/` | Asset manifests; large downloads excluded from Git |
| `data/` | Restored working data and new runtime outputs; excluded from Git |
| `site/` | Generated static demo; excluded from Git |

The application has no Python imports from the larger Study Desk project.
Lecture attribution, recorded CC BY-NC-SA 4.0 notices, and model/library terms
are documented in [third-party notices](THIRD_PARTY_NOTICES.md).
