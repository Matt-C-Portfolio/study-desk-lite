"""Local BGE embeddings for concept candidates and passage retrieval."""

from pathlib import Path

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

MODEL_DIR = Path(__file__).resolve().parents[1] / 'models' / 'bge-base-en-v1.5'
QUERY_PREFIX = 'Represent this sentence for searching relevant passages: '


class Embedder:
    def __init__(self, folder=MODEL_DIR):
        folder = Path(folder)
        self.tokenizer = Tokenizer.from_file(str(folder / 'tokenizer.json'))
        self.tokenizer.no_truncation()
        self.tokenizer.enable_padding(pad_id=0, pad_token='[PAD]')
        options = ort.SessionOptions()
        options.intra_op_num_threads = 4
        self.session = ort.InferenceSession(
            str(folder / 'onnx/model.onnx'),
            sess_options=options,
            providers=['CPUExecutionProvider'],
        )

    def encode(self, texts, *, retrieval_query=False, batch_size=16):
        """Concepts/passages use plain text; RAG questions use the query prefix.

        Callers must split text longer than 512 tokens; nothing is truncated.
        Returned vectors are normalized, so their dot product is cosine similarity.
        """
        if batch_size < 1:
            raise ValueError('batch_size must be positive')
        if any(not isinstance(text, str) or not text.strip() for text in texts):
            raise ValueError('Provide nonempty text for each embedding')
        vectors = []
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            if retrieval_query:
                batch = [QUERY_PREFIX + text for text in batch]
            tokens = self.tokenizer.encode_batch(batch)
            if any(len(item.ids) > 512 for item in tokens):
                raise ValueError(
                    'Text exceeds 512 tokens including prefix and special tokens; split it first'
                )
            inputs = {
                'input_ids': np.array([t.ids for t in tokens], dtype=np.int64),
                'attention_mask': np.array([t.attention_mask for t in tokens], dtype=np.int64),
                'token_type_ids': np.array([t.type_ids for t in tokens], dtype=np.int64),
            }
            # BGE uses the first (CLS) token, not mean pooling.
            cls = self.session.run(['last_hidden_state'], inputs)[0][:, 0]
            vectors.append(cls / np.linalg.norm(cls, axis=1, keepdims=True))
        return np.concatenate(vectors) if vectors else np.empty((0, 768), dtype=np.float32)
