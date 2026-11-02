"""Build the index and answer questions with citations (the RAG pipeline)."""

import json
import re
import time
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np

from .config import INDEX_DIR, Settings, load_sources
from .ingest import chunk_document, iter_documents
from .llm import Ollama
from .retrieval import Index, tokenize

# nomic-embed-text is trained with task prefixes for asymmetric search
DOC_PREFIX = "search_document: "
QUERY_PREFIX = "search_query: "

SYSTEM_PROMPT = """You are Research Copilot, answering questions about Raj Yadav's engineering and research projects.

Rules:
1. Use ONLY the numbered context passages. Never use outside knowledge or invent numbers, names or results.
2. Reuse the passages' own wording, numbers and names.
3. If the passages do not contain the answer, reply exactly: "The documents do not cover this."
4. Be concise: at most 5 sentences or a short bullet list."""

NOT_COVERED = "The documents do not cover this."

# Sentence boundaries: end punctuation before a capital/markup character, or a line break (bullets)
SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+(?=[A-Z`*\"(\[])|\n+")
MODEL_CITATION = re.compile(r"\s*\[\d+\]")
# Share of a sentence's content words that must appear in one passage for it to count as supported;
# on the evaluation answers grounded sentences scored 0.5-1.0 and invented filler 0.0-0.33
SUPPORT_THRESHOLD = 0.5


def attribute(answer: str, passages: List[Dict[str, object]]) -> Dict[str, object]:
    """Ground an answer sentence by sentence: cite the passage sharing most of each sentence's words.

    A small model does not write reliable [n] citations itself, so they are computed here. Sentences that
    no passage supports are returned as unsupported instead of being cited.
    """
    passage_tokens = [set(tokenize(f"{p['heading']} {p['text']}")) for p in passages]
    pieces, sentences, start = [], [], 0
    boundaries = [(m.start(), m.end()) for m in SENTENCE_BREAK.finditer(answer)] + [(len(answer), len(answer))]
    for end, next_start in boundaries:
        sentence = MODEL_CITATION.sub("", answer[start:end]).strip()
        words = set(tokenize(sentence))
        cited = None
        if words and passage_tokens:
            overlaps = [len(words & toks) / len(words) for toks in passage_tokens]
            best = max(range(len(overlaps)), key=overlaps.__getitem__)
            if overlaps[best] >= SUPPORT_THRESHOLD:
                cited = best + 1
            sentences.append({"text": sentence, "passage": cited, "overlap": round(overlaps[best], 2)})
        if cited:
            body, mark = (sentence[:-1], sentence[-1]) if sentence[-1] in ".!?:;" else (sentence, "")
            sentence = f"{body} [{cited}]{mark}"
        pieces.append(sentence)
        pieces.append(answer[end:next_start])
        start = next_start
    return {
        "text": "".join(pieces).strip(),
        "citations": sorted({s["passage"] for s in sentences if s["passage"]}),
        "sentences": sentences,
    }


def build_index(settings: Optional[Settings] = None, log=print) -> Dict[str, object]:
    settings = settings or Settings()
    started = time.perf_counter()
    chunks: List[Dict[str, str]] = []
    per_source: Dict[str, int] = {}
    for source in load_sources():
        docs = list(iter_documents(source))
        per_source[source.label] = per_source.get(source.label, 0) + len(docs)
        for doc in docs:
            chunks.extend(chunk_document(doc, settings.chunk_chars, settings.chunk_overlap))
        log(f"[copilot] {source.label}: {len(docs)} documents")
    log(f"[copilot] {len(chunks)} chunks; embedding with {settings.embed_model} ...")

    # Embeddings are checkpointed by chunk id, so an interrupted build resumes where it stopped
    llm = Ollama(settings)
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = INDEX_DIR / f"embed_cache_{settings.embed_model.replace(':', '_')}.jsonl"
    cache: Dict[str, List[float]] = {}
    if cache_path.exists():
        for line in open(cache_path, encoding="utf-8"):
            row = json.loads(line)
            cache[row["id"]] = row["v"]
    todo = [c for c in chunks if c["id"] not in cache]
    log(f"[copilot] {len(cache)} embeddings cached, {len(todo)} to compute")
    skipped = 0
    with open(cache_path, "a", encoding="utf-8") as out:
        for start in range(0, len(todo), 16):
            batch = todo[start:start + 16]
            vectors = llm.embed_tolerant([f"{DOC_PREFIX}{c['heading']}\n{c['text']}" for c in batch])
            for c, v in zip(batch, vectors):
                if v is None:
                    skipped += 1
                    continue
                cache[c["id"]] = v
                out.write(json.dumps({"id": c["id"], "v": v}) + "\n")
            out.flush()
            if (start // 16) % 16 == 0:
                log(f"[copilot] embedded {min(start + 16, len(todo))}/{len(todo)}")

    # Chunks that could not be embedded stay out of the index rather than getting a fake vector
    chunks = [c for c in chunks if c["id"] in cache]
    index = Index(chunks, Index.normalize(np.asarray([cache[c["id"]] for c in chunks], dtype=np.float32)))
    index.save(INDEX_DIR)

    manifest = {
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "documents": per_source,
        "chunks": len(chunks),
        "skipped_chunks": skipped,
        "embed_model": settings.embed_model,
        "dimensions": int(index.vectors.shape[1]),
        "seconds": round(time.perf_counter() - started, 1),
    }
    (INDEX_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    log(f"[copilot] index saved: {manifest}")
    return manifest


class Copilot:
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or Settings()
        self.llm = Ollama(self.settings)
        self.index = Index.load(INDEX_DIR)
        manifest_path = INDEX_DIR / "manifest.json"
        self.manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}

    def retrieve(self, question: str, top_k: Optional[int] = None) -> List[Dict[str, object]]:
        vector = self.llm.embed([QUERY_PREFIX + question])[0]
        return self.index.search(question, vector, top_k or self.settings.top_k,
                                 self.settings.candidates, self.settings.rrf_k)

    def ask(self, question: str) -> Dict[str, object]:
        started = time.perf_counter()
        passages = self.retrieve(question)
        retrieval_seconds = round(time.perf_counter() - started, 2)
        context = "\n\n".join(
            f"[{i}] ({p['source']} · {p['path']}{' · ' + p['heading'] if p['heading'] else ''})\n{p['text']}"
            for i, p in enumerate(passages, start=1)
        )
        reply = self.llm.chat(SYSTEM_PROMPT, f"Context passages:\n\n{context}\n\nQuestion: {question}")
        abstained = reply["text"].strip().startswith(NOT_COVERED)
        grounded = {"text": NOT_COVERED, "citations": [], "sentences": []} if abstained else attribute(reply["text"], passages)
        return {
            "question": question,
            "answer": grounded["text"],
            "raw_answer": reply["text"],
            "abstained": abstained,
            "citations": grounded["citations"],
            "grounding": {
                "sentences": len(grounded["sentences"]),
                "supported": sum(1 for s in grounded["sentences"] if s["passage"]),
                "unsupported": [s["text"] for s in grounded["sentences"] if not s["passage"]],
            },
            "sources": [{k: p[k] for k in ("source", "path", "heading", "text", "score", "bm25", "cosine")}
                        for p in passages],
            "model": self.settings.chat_model,
            "embed_model": self.settings.embed_model,
            "retrieval_seconds": retrieval_seconds,
            "generation_seconds": reply["seconds"],
            "tokens_per_second": reply["tokens_per_second"],
        }
