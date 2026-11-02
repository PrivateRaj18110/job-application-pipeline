"""Thin client for the local Ollama server (open-source embedding and chat models)."""

import time
from typing import Dict, List, Optional

import httpx

from .config import Settings


class OllamaError(RuntimeError):
    pass


class Ollama:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = httpx.Client(base_url=settings.ollama_url, timeout=httpx.Timeout(600.0, connect=5.0))

    def available_models(self) -> List[str]:
        try:
            response = self.client.get("/api/tags")
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise OllamaError(f"Ollama is not reachable at {self.settings.ollama_url}: {e}") from e
        return [m["name"] for m in response.json().get("models", [])]

    def _embed_batch(self, batch: List[str], attempts: int = 3) -> List[List[float]]:
        """Retries transient failures; Ollama restarts a crashed model runner on the next request."""
        error = ""
        for attempt in range(attempts):
            try:
                response = self.client.post("/api/embed", json={"model": self.settings.embed_model, "input": batch})
                if response.status_code == 200:
                    return response.json()["embeddings"]
                error = f"{response.status_code}: {response.text[:200]}"
            except httpx.HTTPError as e:
                error = str(e)
            time.sleep(3 * (attempt + 1))
        raise OllamaError(f"Embedding failed after {attempts} attempts ({error})")

    def embed(self, texts: List[str], batch_size: int = 16) -> List[List[float]]:
        vectors: List[List[float]] = []
        for start in range(0, len(texts), batch_size):
            vectors.extend(self._embed_batch(texts[start:start + batch_size]))
        return vectors

    def embed_tolerant(self, texts: List[str]) -> List[Optional[List[float]]]:
        """Like embed(), but isolates inputs that keep failing and returns None for them."""
        try:
            return self._embed_batch(texts)
        except OllamaError:
            if len(texts) == 1:
                return [None]
            mid = len(texts) // 2
            return self.embed_tolerant(texts[:mid]) + self.embed_tolerant(texts[mid:])

    def chat(self, system: str, user: str) -> Dict[str, object]:
        started = time.perf_counter()
        response = self.client.post("/api/chat", json={
            "model": self.settings.chat_model,
            "stream": False,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "options": {
                "temperature": self.settings.temperature,
                "num_ctx": self.settings.num_ctx,
                "num_predict": self.settings.max_answer_tokens,
            },
        })
        if response.status_code != 200:
            raise OllamaError(f"Chat failed ({response.status_code}): {response.text[:200]}")
        data = response.json()
        eval_count = data.get("eval_count") or 0
        eval_ns = data.get("eval_duration") or 0
        return {
            "text": data["message"]["content"].strip(),
            "seconds": round(time.perf_counter() - started, 1),
            "tokens": eval_count,
            "tokens_per_second": round(eval_count / (eval_ns / 1e9), 1) if eval_ns else None,
        }
