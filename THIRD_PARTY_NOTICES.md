# Sources and third-party notices

## Lecture materials

The curated corpus uses MIT OpenCourseWare lectures by Eric Grimson, John Guttag,
and Patrick Henry Winston. `lecture-presets.json` records each lecture's title,
URL, course source, creators, and the recorded license evidence. The source
materials and adaptations carry CC BY-NC-SA 4.0 notices except where separately
credited material has different terms. Keep those notices with redistributed
examples and question-bank materials.

- [MIT OCW terms](https://ocw.mit.edu/pages/privacy-and-terms-of-use/)
- [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/)
- `evaluation/question-bank-v1/README.txt` and `sources.json`: question-bank attribution.
- `baseline/notes.md` and `baseline/settings.json`: saved generated guide and source.
- `evaluation/dataset/`: recorded captions, metadata, and experiment outputs. The
  restored lecture metadata and original artifacts retain their source notices; the
  lecture-material terms above also apply to this bundled corpus and its adaptations.

## Models and runtime

Model weights and llama.cpp binaries are downloaded separately, not redistributed
in this source package. Preserve their upstream license notices when downloading.

- [DeepSeek R1](https://github.com/deepseek-ai/DeepSeek-R1): distilled model family.
- [Bartowski GGUFs](https://huggingface.co/bartowski): exact repositories, revisions,
  filenames and hashes are in `models/downloads.json` and `models/manifest.json`.
- [BAAI BGE base en v1.5](https://huggingface.co/BAAI/bge-base-en-v1.5): the manifest
  and MIT license are retained under `models/bge-base-en-v1.5/`.
- [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper) and
  [large-v3 weights](https://huggingface.co/Systran/faster-whisper-large-v3).
- [llama.cpp](https://github.com/ggml-org/llama.cpp): runtime release records are
  in `runtime/manifest.json`.

## Browser assets

The vendored Marked, DOMPurify, and KaTeX files retain their license notices in
`study_desk/web/vendor/`. The UNC logo in the interface is an institutional mark;
it is not project-owned artwork and does not imply endorsement.

These attribution notes do not relicense third-party materials or grant rights to
institutional marks.
