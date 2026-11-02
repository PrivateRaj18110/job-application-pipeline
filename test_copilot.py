"""
Test Suite: test_copilot.py
Offline verification of the Research Copilot RAG pipeline (no Ollama, no network).
Validates:
1. Secret redaction before indexing
2. Heading-aware chunking
3. BM25 ranking and reciprocal rank fusion
4. Hybrid search over a toy index with fake embeddings
5. Grounded answering: sentences cited by source overlap, unsupported sentences flagged, abstention detected
"""

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import numpy as np

from research_copilot.ingest import chunk_document, redact
from research_copilot.retrieval import BM25, Index, reciprocal_rank_fusion
from research_copilot.pipeline import NOT_COVERED, Copilot
from research_copilot.config import Settings

DOCS = [
    {"source": "Algo", "path": "ops/receiver.md", "heading": "Receiver",
     "text": "VM1 on Google Cloud sends monitoring batches to POST /ops/api/agent/batch over TLS."},
    {"source": "Algo", "path": "ops/ai.md", "heading": "AI platform",
     "text": "The assistant uses Claude through a pluggable provider; without a key the null provider answers."},
    {"source": "LLS", "path": "README.md", "heading": "Execution",
     "text": "Real-money orders are disabled; the order manager is tested against a deterministic mock broker."},
]


def toy_index() -> Index:
    # 3-dimensional fake embeddings: one axis per topic
    vectors = Index.normalize(np.eye(3, dtype=np.float32))
    return Index([dict(d, id=str(i)) for i, d in enumerate(DOCS)], vectors)


class FakeLLM:
    def __init__(self, reply: str):
        self.reply = reply
        self.last_prompt = ""

    def embed(self, texts):
        q = texts[0].lower()
        return [[1.0 if "batch" in q or "vm1" in q else 0.0, 1.0 if "assistant" in q else 0.0, 1.0 if "order" in q else 0.0]]

    def chat(self, system, user):
        self.last_prompt = user
        return {"text": self.reply, "seconds": 0.1, "tokens": 5, "tokens_per_second": 50.0}


def make_copilot(reply: str) -> Copilot:
    copilot = Copilot.__new__(Copilot)
    copilot.settings = Settings(top_k=2)
    copilot.llm = FakeLLM(reply)
    copilot.index = toy_index()
    copilot.manifest = {}
    return copilot


def test_redaction():
    text = "api_key: abc123secret\nPASSWORD=hunter2hunter\nsha " + "a" * 64 + "\naccess tokens are short-lived"
    out = redact(text)
    assert "abc123secret" not in out and "hunter2hunter" not in out and "a" * 64 not in out
    assert "access tokens are short-lived" in out, "Ordinary prose must not be redacted"
    print("  [PASS] Keys, passwords and digests redacted; normal prose kept")


def test_chunking():
    doc = {"source": "S", "path": "doc.md", "text": "# Title\nIntro paragraph long enough to keep around here.\n\n## Part A\n" + ("Alpha sentence. " * 120) + "\n\n## Part B\nBeta paragraph that is also long enough."}
    chunks = chunk_document(doc, size=500, overlap=50)
    headings = {c["heading"] for c in chunks}
    assert "Title > Part A" in headings and "Title > Part B" in headings, headings
    assert all(len(c["text"]) <= 500 for c in chunks)
    assert len({c["id"] for c in chunks}) == len(chunks), "Chunk ids must be unique"
    print(f"  [PASS] {len(chunks)} chunks with heading paths {sorted(headings)}")


def test_bm25_and_rrf():
    bm25 = BM25([d["text"] for d in DOCS])
    scores = bm25.scores("mock broker orders")
    assert int(np.argmax(scores)) == 2
    fused = reciprocal_rank_fusion([[2, 0, 1], [2, 1]], k=60)
    assert max(fused, key=fused.get) == 2 and fused[1] > fused[0]
    print("  [PASS] BM25 ranks the right passage; RRF rewards agreement across rankers")


def test_hybrid_search():
    index = toy_index()
    hits = index.search("How does VM1 send monitoring batches?", [1.0, 0.0, 0.0], top_k=2)
    assert hits[0]["path"] == "ops/receiver.md" and hits[0]["cosine"] == 1.0
    print("  [PASS] Hybrid search returns the receiver doc first with its scores")


def test_grounded_answer():
    # The model's own (wrong) [2] is replaced by the passage the sentence actually came from
    copilot = make_copilot("VM1 posts batches to /ops/api/agent/batch over TLS [2]. It also predicts tomorrow's weather.")
    out = copilot.ask("How does VM1 send monitoring batches?")
    assert out["answer"].startswith("VM1 posts batches to /ops/api/agent/batch over TLS [1]."), out["answer"]
    assert out["citations"] == [1] and not out["abstained"]
    assert out["grounding"]["supported"] == 1 and out["grounding"]["unsupported"] == ["It also predicts tomorrow's weather."]
    assert "[1] (Algo · ops/receiver.md" in copilot.llm.last_prompt, "Prompt must carry numbered passages"

    refusing = make_copilot(NOT_COVERED)
    out = refusing.ask("What is the capital of France?")
    assert out["abstained"] and out["citations"] == [] and out["grounding"]["sentences"] == 0
    print("  [PASS] Sentences cited by source overlap, invented sentence flagged, abstention detected")


def run_all_tests() -> bool:
    tests = [test_redaction, test_chunking, test_bm25_and_rrf, test_hybrid_search, test_grounded_answer]
    results = {}
    for fn in tests:
        print(f"\n[*] {fn.__name__}")
        try:
            fn()
            results[fn.__name__] = "PASSED"
        except Exception as e:
            print(f"  [FAIL] {type(e).__name__}: {e}")
            results[fn.__name__] = f"FAILED: {e}"
    print("\n" + "=" * 60)
    for name, result in results.items():
        print(f"{'✅' if result == 'PASSED' else '❌'} {name:24}: {result}")
    return all(r == "PASSED" for r in results.values())


if __name__ == "__main__":
    sys.exit(0 if run_all_tests() else 1)
