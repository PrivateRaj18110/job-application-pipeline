"""Hybrid retrieval: BM25 keyword search + dense embeddings, fused with reciprocal rank fusion."""

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import numpy as np

TOKEN = re.compile(r"[a-z0-9][a-z0-9_.+-]*[a-z0-9]|[a-z0-9]")
STOPWORDS = set("""a an and are as at be by for from has have how i in is it its of on or that the this to was
were what when where which who why will with does do did can should would""".split())


def tokenize(text: str) -> List[str]:
    return [t for t in TOKEN.findall(text.lower()) if t not in STOPWORDS]


class BM25:
    def __init__(self, docs: Sequence[str], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.tokens = [tokenize(d) for d in docs]
        self.lengths = np.array([len(t) for t in self.tokens], dtype=np.float32)
        self.avg_len = float(self.lengths.mean()) if len(self.lengths) else 0.0
        self.tf = [Counter(t) for t in self.tokens]
        df = Counter(term for toks in self.tokens for term in set(toks))
        n = len(docs)
        self.idf = {term: math.log(1 + (n - f + 0.5) / (f + 0.5)) for term, f in df.items()}

    def scores(self, query: str) -> np.ndarray:
        out = np.zeros(len(self.tokens), dtype=np.float32)
        for term in set(tokenize(query)):
            idf = self.idf.get(term)
            if idf is None:
                continue
            for i, tf in enumerate(self.tf):
                f = tf.get(term)
                if f:
                    norm = f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.lengths[i] / self.avg_len))
                    out[i] += idf * norm
        return out


def reciprocal_rank_fusion(rankings: List[List[int]], k: int = 60) -> Dict[int, float]:
    """Each list holds chunk indices best-first; RRF score = sum of 1 / (k + rank)."""
    fused: Dict[int, float] = {}
    for ranking in rankings:
        for rank, idx in enumerate(ranking, start=1):
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (k + rank)
    return fused


class Index:
    def __init__(self, chunks: List[Dict[str, str]], vectors: Optional[np.ndarray]):
        self.chunks = chunks
        self.vectors = vectors
        self.bm25 = BM25([f"{c['heading']} {c['text']}" for c in chunks])

    @staticmethod
    def normalize(vectors: np.ndarray) -> np.ndarray:
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        return vectors / np.clip(norms, 1e-12, None)

    def save(self, folder: Path) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        with open(folder / "chunks.jsonl", "w", encoding="utf-8") as f:
            for c in self.chunks:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")
        if self.vectors is not None:
            np.save(folder / "vectors.npy", self.vectors.astype(np.float32))

    @classmethod
    def load(cls, folder: Path) -> "Index":
        chunks = [json.loads(line) for line in open(folder / "chunks.jsonl", encoding="utf-8")]
        vec_path = folder / "vectors.npy"
        vectors = np.load(vec_path) if vec_path.exists() else None
        return cls(chunks, vectors)

    def search(self, query: str, query_vector: Optional[Sequence[float]], top_k: int = 5,
               candidates: int = 30, rrf_k: int = 60) -> List[Dict[str, object]]:
        keyword = self.bm25.scores(query)
        rankings = [[int(i) for i in np.argsort(-keyword)[:candidates] if keyword[i] > 0]]
        dense = None
        if self.vectors is not None and query_vector is not None:
            q = self.normalize(np.asarray([query_vector], dtype=np.float32))[0]
            dense = self.vectors @ q
            rankings.append([int(i) for i in np.argsort(-dense)[:candidates]])

        fused = reciprocal_rank_fusion(rankings, k=rrf_k)
        best = sorted(fused, key=fused.get, reverse=True)[:top_k]
        return [{
            **self.chunks[i],
            "score": round(fused[i], 4),
            "bm25": round(float(keyword[i]), 3),
            "cosine": round(float(dense[i]), 3) if dense is not None else None,
        } for i in best]
