"""Minimal retrieval (RAG) for the voice agent.

Index layout (built by rag_ingest.py):
    <index_dir>/chunks.json    - list of {"text": ..., "source": ...}
    <index_dir>/embeddings.npy - float32 matrix, L2-normalized, one row per chunk

Embeddings are served by a llama.cpp server running with --embedding
(see start_embedding_server.sh). The same embedding model must be used
for ingestion and for queries.
"""

import json
import os
import time

import httpx
import numpy as np


def embed_texts(texts, embedding_server_url, client=None, timeout=30.0):
    """Embed a list of texts via an OpenAI-compatible /embeddings endpoint.

    Returns a L2-normalized float32 numpy matrix (one row per text).
    """
    own_client = client is None
    if own_client:
        client = httpx.Client(timeout=timeout)
    try:
        response = client.post(
            f"{embedding_server_url.rstrip('/')}/embeddings",
            json={"model": "embedding", "input": texts},
        )
        response.raise_for_status()
        data = response.json()["data"]
        data.sort(key=lambda d: d["index"])
        embeddings = np.array([d["embedding"] for d in data], dtype=np.float32)
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return embeddings / norms
    finally:
        if own_client:
            client.close()


class RagRetriever:
    """Loads the index and returns relevant chunks for a query."""

    def __init__(self, index_dir, embedding_server_url,
                 top_k=2, min_score=0.35, max_context_chars=1200):
        chunks_file = os.path.join(index_dir, "chunks.json")
        embeddings_file = os.path.join(index_dir, "embeddings.npy")
        if not os.path.isfile(chunks_file) or not os.path.isfile(embeddings_file):
            raise FileNotFoundError(
                f"RAG index not found in '{index_dir}'. "
                f"Build it first with rag_ingest.py.")

        with open(chunks_file, "r", encoding="utf-8") as f:
            self.chunks = json.load(f)
        self.embeddings = np.load(embeddings_file)
        if len(self.chunks) != self.embeddings.shape[0]:
            raise ValueError(
                f"Index mismatch: {len(self.chunks)} chunks vs "
                f"{self.embeddings.shape[0]} embeddings. Re-run rag_ingest.py.")

        self.embedding_server_url = embedding_server_url
        self.top_k = top_k
        self.min_score = min_score
        self.max_context_chars = max_context_chars
        self.client = httpx.Client(timeout=10.0)

        # Check that the embedding server is reachable, allowing it time to
        # come up when everything starts together at boot (off-grid autostart).
        for attempt in range(30):
            try:
                embed_texts(["ping"], self.embedding_server_url, client=self.client)
                break
            except Exception:
                if attempt == 29:
                    raise
                print(f">> Waiting for embedding server at {self.embedding_server_url}... ({attempt + 1}/30)")
                time.sleep(1.0)

    def retrieve(self, query):
        """Return list of (score, chunk) for the query, best first."""
        query_embedding = embed_texts([query], self.embedding_server_url,
                                      client=self.client)[0]
        scores = self.embeddings @ query_embedding
        order = np.argsort(scores)[::-1][:self.top_k]
        return [(float(scores[i]), self.chunks[i])
                for i in order if scores[i] >= self.min_score]

    def get_context(self, query):
        """Format retrieved chunks as a context block, or None if no match."""
        results = self.retrieve(query)
        if not results:
            return None
        lines = ["Background information (use only if relevant):"]
        total_chars = 0
        for _score, chunk in results:
            text = chunk["text"].strip()
            if total_chars + len(text) > self.max_context_chars and total_chars > 0:
                break
            total_chars += len(text)
            lines.append(f"- {text}")
        return "\n".join(lines)

    def close(self):
        self.client.close()
