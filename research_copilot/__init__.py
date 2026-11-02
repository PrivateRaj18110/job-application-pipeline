"""
Research Copilot: retrieval-augmented generation (RAG) over my own project documentation,
answered by an open-source LLM running locally through Ollama.

Pipeline: markdown docs -> heading-aware chunks (secrets redacted) -> hybrid retrieval
(BM25 + dense embeddings, fused with reciprocal rank fusion) -> answer from the local LLM ->
grounding check that cites each sentence's source passage and flags sentences no passage supports.

Run with:
  python -m research_copilot build                  # index the sources in copilot_sources.json
  python -m research_copilot ask "your question"
  python -m research_copilot eval                   # retrieval + answer quality report
"""
