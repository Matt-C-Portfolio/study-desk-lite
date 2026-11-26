# Run Study Desk Lite on Windows

These steps open the saved project on your computer. You need Python 3.11
(with the `py` launcher) and PostgreSQL 17 installed.

## 1. Install the Python packages

Download this repository. Open PowerShell in its folder and run:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-windows.lock.txt
```

## 2. Create the database

Open **SQL Shell (psql)** from the Start menu. Sign in as `postgres` using the
password you chose when installing PostgreSQL. Run:

```sql
CREATE ROLE study_desk_lite LOGIN;
\password study_desk_lite
CREATE DATABASE study_desk_lite OWNER study_desk_lite;
```

The second command asks you to choose a password for the app.

## 3. Connect the app

In your Windows user folder, create a folder named `.study-desk-lite`.
Inside it, save a file named `database.json` containing:

```json
{
  "dsn": "host=localhost dbname=study_desk_lite user=study_desk_lite password=YOUR_PASSWORD"
}
```

Replace `YOUR_PASSWORD` with the app password from step 2.

## 4. Load the included project

Back in PowerShell, run:

```powershell
.\.venv\Scripts\python.exe scripts/dataset.py restore
.\study-desk.cmd ui
```

Open [localhost:8788](http://127.0.0.1:8788). The saved lectures, guides, graphs,
and answers are ready to browse.

Run `restore` only once, with an empty database and no existing data in `data/`.
Next time, keep PostgreSQL running and start with `.\study-desk.cmd ui`.

## Optional: generate new results

Local generation requires an NVIDIA GPU. Download these files:

| Download | Where it goes |
| --- | --- |
| [DeepSeek 1.5B](https://huggingface.co/bartowski/DeepSeek-R1-Distill-Qwen-1.5B-GGUF/resolve/9cc28b17e86fa2415fcb070f8ee5ec27c965aa61/DeepSeek-R1-Distill-Qwen-1.5B-Q4_K_M.gguf) | Save in `models/`, keeping the filename. |
| [llama.cpp](https://github.com/ggml-org/llama.cpp/releases/download/b10059/llama-b10059-bin-win-cuda-12.4-x64.zip) and [CUDA DLLs](https://github.com/ggml-org/llama.cpp/releases/download/b10059/cudart-llama-bin-win-cuda-12.4-x64.zip) | Extract both into `runtime/llama.cpp/`. |

Make sure `llama-server.exe` and the DLLs are directly inside that folder.
Select **1.5B** in the app to generate guides. The recorded 7B and 14B downloads are
listed in [models/downloads.json](../models/downloads.json); save them in the same `models/` folder.

For new graphs and retrieval-based answers, also download the embedding files:

```powershell
$revision = "a5beb1e3e68b9ab74eb54cfd186867f64f240e1a"
.\.venv\Scripts\hf.exe download BAAI/bge-base-en-v1.5 `
  --revision $revision `
  --include "onnx/model.onnx" "*.json" "LICENSE" "README.md" `
  --local-dir models/bge-base-en-v1.5
```

After adding or changing transcripts, update the retrieval index:

```powershell
.\.venv\Scripts\python.exe -m study_desk.retrieval index
```

Build each model's graph from the graph tab.

For OpenAI, save your API key in
`%USERPROFILE%\.config\study-desk-lite\openai.key` and restart the app.
New OpenAI runs require model access and incur API charges.
