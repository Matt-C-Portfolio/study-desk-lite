# Installation and first run

To review the project without installing anything, use the
[recorded project demo](https://Matt-C-Portfolio.github.io/study-desk-lite/).
It includes the saved library, guide attempts, graphs, and all 1,920 comparison answers.
The setup below is for running the local application and generating new results.

Run commands in PowerShell from the Study Desk Lite repository root. The supported
local setup is **Windows x64, Python 3.11, PostgreSQL 17, and an NVIDIA GPU**.
The application has not been verified end-to-end on macOS, Linux, or a CPU-only machine.
The batch launcher, packaged llama.cpp runtime, and experiment runners are
Windows-specific. The UI's optional audio transcription action uses CUDA.

## 1. Python environment

Install Python 3.11 with the **Python launcher for Windows** enabled, and install
PostgreSQL 17. Open a new PowerShell window and check `py -3.11 --version` before
continuing. If `py` is not recognized, rerun the Python installer and enable its
launcher component. The launcher selects Python 3.11 to create the environment;
subsequent commands use that environment's executable directly.
No parent Study Desk checkout is needed.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-windows.lock.txt
.\.venv\Scripts\python.exe -m pip check
```

The lock file records the working Python environment, including transitive dependencies.
`requirements.txt` lists the direct dependencies and permits pip to resolve their
transitive dependencies. Neither file contains model weights. There is no need to
activate the environment or change PowerShell execution policy.

For optional GPU audio transcription, also install:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-cuda.txt
```

This installs the Python CUDA libraries used by Faster-Whisper. It does not install the
NVIDIA driver or the separate DLLs used by llama.cpp. Captions do not need Whisper
weights or these optional CUDA Python packages.

## 2. PostgreSQL

Keep PostgreSQL running. Use SQL Shell (psql), or the `psql.exe` from your PostgreSQL
installation, to connect as the administrator. Create a dedicated application role and
database; `\password` prompts without embedding a password in a command:

```sql
CREATE ROLE study_desk_lite LOGIN;
\password study_desk_lite
CREATE DATABASE study_desk_lite OWNER study_desk_lite;
```

Connect to that database as `study_desk_lite`. The role must be able to create tables in
its selected schema. The database owner can also create the disposable schemas used by
the test suite. Do not point Lite at the main Study Desk database.

Create `%USERPROFILE%\.study-desk-lite\database.json` outside the repository:

```json
{"dsn": "host=localhost port=5432 dbname=study_desk_lite user=study_desk_lite password=YOUR_PASSWORD"}
```

Use valid PostgreSQL connection-string quoting if the password contains spaces or
quotes, and valid JSON escaping inside the file. Alternatively, set
`STUDY_DESK_LITE_DATABASE_URL` in the launching process. It takes precedence over the
JSON file. PostgreSQL's normal password-file mechanism can also be used with a DSN that
omits `password`.

The application creates its tables automatically on startup from `study_desk/schema.sql`
and `study_desk/graph_schema.sql`; no separate migration command is necessary. The app
does **not** load `.env` files.

### Load the included project

With the app closed, restore the recorded ten-lecture dataset into your empty database
and empty (or absent) `data/` directory, then launch:

```powershell
.\.venv\Scripts\python.exe scripts/dataset.py restore
.\study-desk.cmd ui
```

Open <http://127.0.0.1:8788>. The library, saved guides, graphs, and the individual answers
linked from the comparison are now available. **You can browse these saved results
without downloading models, installing llama.cpp, or supplying an API key.** Video
playback still streams from YouTube and needs internet. The dataset contains saved
captions and outputs, not video or audio downloads.

Restore checks the archive hashes, loads the database, and adjusts its file paths to
your local data directory. It never overwrites a populated database or nonempty data
directory. Existing users with the recorded library do not need to restore it again.
The [dataset description](../evaluation/README.md#included-dataset) explains its contents.

Continue with steps 3-5 when you want to generate new results locally. For a deliberately
empty library, skip the restore command and start the app normally.

## 3. Local language model

Start with one model. The experiment uses these exact Q4_K_M files:

| Model | Weight download | Hugging Face repository | Pinned revision |
| --- | ---: | --- | --- |
| 1.5B | 1.12 GB | `bartowski/DeepSeek-R1-Distill-Qwen-1.5B-GGUF` | `9cc28b17e86fa2415fcb070f8ee5ec27c965aa61` |
| 7B | 4.68 GB | `bartowski/DeepSeek-R1-Distill-Qwen-7B-GGUF` | `361004151d4f4f6b446dc5e6d46fbf4422a80d5f` |
| 14B | 8.99 GB | `bartowski/DeepSeek-R1-Distill-Qwen-14B-GGUF` | `9f5d77d401799416e0702290a691038b44012e0c` |

Download the smallest model with the Hugging Face CLI installed by the environment:

```powershell
.\.venv\Scripts\hf.exe download bartowski/DeepSeek-R1-Distill-Qwen-1.5B-GGUF DeepSeek-R1-Distill-Qwen-1.5B-Q4_K_M.gguf --revision 9cc28b17e86fa2415fcb070f8ee5ec27c965aa61 --local-dir models
```

For 7B or 14B, substitute the repository, filename, and revision from the table.
`models/downloads.json` provides direct download URLs; `models/manifest.json` records
the original byte sizes and SHA-256 hashes.

Weight size is **not** the GPU memory requirement. The runtime uses a 32K context, Q8 KV
cache, and GPU offload. The tested machine has an RTX 3090 Ti (24 GB VRAM) and
about 32 GB system RAM; this is a tested configuration, not a minimum specification. A
smaller-hardware minimum has not been established.

## 4. llama.cpp runtime

The currently installed runtime reports `b10059`, commit `11fd0a6fb`. Download these two
assets from the [b10059
release](https://github.com/ggml-org/llama.cpp/releases/tag/b10059):

- `llama-b10059-bin-win-cuda-12.4-x64.zip`
- `cudart-llama-bin-win-cuda-12.4-x64.zip`

Extract both into `runtime/llama.cpp/`. The executable must be at
`runtime/llama.cpp/llama-server.exe`, with its companion DLLs beside it, rather than in
an extra nested folder. Keep your NVIDIA driver installed and working.
`runtime/manifest.json` records release URLs and archive hashes. Compare a downloaded
archive using `Get-FileHash -Algorithm SHA256 <archive-path>` before extracting.

```powershell
.\runtime\llama.cpp\llama-server.exe --version
```

The app starts this runtime on `127.0.0.1:8800` when a local model is selected and stops
it after the job. Do not start a second server on that port. The original experiment did
not pin a runtime binary hash, so this installed build is not proof of the exact binary
used for every historical run.

## 5. BGE embeddings for graphs and retrieval

Guide generation and model-only answers do not need BGE. Graph construction and the
three retrieval modes do. Download the pinned BGE files:

```powershell
.\.venv\Scripts\hf.exe download BAAI/bge-base-en-v1.5 onnx/model.onnx tokenizer.json config.json tokenizer_config.json special_tokens_map.json 1_Pooling/config.json LICENSE README.md --revision a5beb1e3e68b9ab74eb54cfd186867f64f240e1a --local-dir models/bge-base-en-v1.5
```

The ONNX weights are about 436 MB. The source, revision, and file hashes are in
`models/bge-base-en-v1.5/manifest.json`. Embeddings run on CPU. No model is downloaded
automatically while the app processes a lecture.

## 6. Check and launch

```powershell
.\.venv\Scripts\python.exe scripts/check_setup.py --database --embeddings
.\study-desk.cmd ui
```

Open <http://127.0.0.1:8788>. The setup checker defaults to 1.5B; use `--model 7B` or
`--model 14B` to check another installation. Add `--verify-models` to check weight
hashes. File checks alone do not prove the GPU can load a model.

To process additional lectures or generate new results:

1. Choose a curated lecture or paste a permitted YouTube URL.
2. Check captions and select the saved transcript.
3. Select the installed model and generate one study guide.
4. Open the saved guide in the library. Failed attempts remain visible.
5. For retrieval Q&A, index the selected transcripts from another terminal:

```powershell
.\.venv\Scripts\python.exe -m study_desk.retrieval index
```

Choose RAG in Ask Study Desk. For graph-only or RAG + graph, build the selected system's
graph in the graph tab first. Graphs use successful saved extractions; the experiment's
graphs span the ten curated lectures. Re-index if you change the selected transcript.
Only one local processing job runs at a time.

To inspect retrieval without generating an answer:

```powershell
.\.venv\Scripts\python.exe -m study_desk.retrieval search "How does alpha beta pruning work?" --top-k 5
```

For corpus settings, historical batch prerequisites, and portable table commands, see
[recorded experiments](../evaluation/README.md).

 ## Optional audio transcription

The corpus experiment used saved captions. Whisper is optional. Download the
CTranslate2-compatible [Systran
weights](https://huggingface.co/Systran/faster-whisper-large-v3):

```powershell
.\.venv\Scripts\hf.exe download Systran/faster-whisper-large-v3 model.bin config.json tokenizer.json vocabulary.json preprocessor_config.json README.md --revision edaa852ec7e145841d8ffdb056a99866b5f0a478 --local-dir models/whisper/large-v3
.\.venv\Scripts\python.exe scripts/check_setup.py --whisper
```

The weights are about 3.09 GB. This revision identifies a setup download; no Whisper
hash was recorded for the caption-based experiment. The UI transcription action requires
CUDA. Standalone transcription supports CPU explicitly:

```powershell
.\study-desk.cmd transcribe lecture.mp3 --output data/lecture.txt --device cpu
```

CPU transcription does not establish CPU support for the complete UI/model pipeline.
YouTube fetching and playback need internet; local inference does not.

## Optional OpenAI route

Local generation does not need an API key. The optional API route sends source text to
OpenAI and incurs charges. Save the key alone in
`%USERPROFILE%\.config\study-desk-lite\openai.key`, or set `OPENAI_API_KEY` in the
launching process, then restart the UI and select OpenAI.

The historical pipeline names are `gpt-5.6-luna` and `gpt-5.6-terra`, as recorded in
`study_desk/openai_model.py`. Account availability and those historical request options
must be checked before a new API experiment; access is not guaranteed. Do not silently
substitute models and label the outputs a reproduction of the original experiment. Saved
costs use the recorded pricing assumptions, not live prices. The saved baseline is
readable without a key or paid request.

## Tests and troubleshooting

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The small BGE tokenizer is bundled for a passage-window test; the embedding weights are
not required by the tests. The tests need PostgreSQL and permission to create/drop
temporary schemas. They use isolated schemas and temporary directories, mocked
inference, and no paid API calls. Passing them is not an end-to-end GPU or YouTube test.

| Symptom | Check |
| --- | --- |
| Database connection fails | PostgreSQL service, role/password, port, and the user config file; run `check_setup.py --database`. |
| Model/runtime missing | Exact filename and directory above; select a model that is installed. |
| Runtime exits or times out | The run's `runtime.log`, companion CUDA DLLs, available VRAM, and port 8800. |
| Graph/RAG cannot load embeddings | Pinned ONNX weights and tokenizer under `models/bge-base-en-v1.5/`. |
| Captions/download fail | Network access, video availability, and YouTube restrictions; a blocked request does not mean captions are absent. |
| Port 8788 is occupied | Use `.\study-desk.cmd ui --port 8789`; the historical batch runner still assumes 8788. |
| Saved answer links do not open | Restore the included dataset into an empty installation and launch using the same `STUDY_DESK_LITE_DATA` directory. The comparison links use the included answer IDs. |
| Restore refuses existing data | It protects your current library. Keep it, or select a separate empty database and data directory; do not delete working data to rerun setup. |

Runtime files default to `data/`. Set `STUDY_DESK_LITE_DATA` before launch to use
another absolute directory. The historical experiment runners assume the default `data/`
location. Set this variable before both restore and launch when using a custom data
directory. Restore rebases database file references to that directory. Archived research
JSON retains original paths for provenance; do not use those historical paths to resume
an old experiment on another machine.

## Prepare a submission copy

```powershell
.\.venv\Scripts\python.exe scripts/package_submission.py --output ..\study-desk-lite-submission
```

Choose a new directory outside this repository. The script copies selected source,
documentation, examples, results, and the complete compressed dataset, and records file hashes. It leaves the
working installation unchanged. Omit `--output` to inspect the file list. It does not
initialize Git, stage files, or publish the project.

## Rebuild the static demo

The GitHub Pages workflow builds the demo from the included dataset using Python 3.11's
standard library. No database, model, API key, or local `data/` directory is needed.
On each push to `main`, it uploads only the generated website and publishes it to Pages.
The repository's Pages publishing source must be **GitHub Actions**.

To produce a separate local copy:

```powershell
.\.venv\Scripts\python.exe scripts/build_static.py --output ..\study-desk-lite-demo
```

Choose a new output directory. The generated site uses normal static files and relative
asset paths, so it works at a domain root or a GitHub project subdirectory. Serve it with
an ordinary static web server to preview it; opening `index.html` as a `file://` URL is
not supported because the browser fetches saved JSON files.

The static adapter blocks write requests and disables generation/removal controls.
All inference and database code remains in the local app. The build does not change
the archived experiment or its source hashes. Check its route adapter after building:

```powershell
node tests/static_transport.cjs ..\study-desk-lite-demo
```
