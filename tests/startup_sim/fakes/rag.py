"""Fake RagRetriever: index load time, upstream's 30 x 1 s wait for the embedding server."""
import simworld as S


class RagRetriever:
    def __init__(self, index_dir, embedding_server_url, top_k=2, min_score=0.35, max_context_chars=1200):
        S.sleep(S.W.jit(1.5, 'rag_load'))
        self.chunks = [None] * 8082
        for attempt in range(30):
            S.sleep(0.02)
            if S.W.embed_ready():
                break
            if attempt == 29:
                raise ConnectionError(f"[sim] embedding server at {embedding_server_url} unreachable")
            print(f">> Waiting for embedding server at {embedding_server_url}... ({attempt + 1}/30)")
            S.sleep(1.0)

    def get_context(self, query):
        if not S.W.embed_ready():
            raise ConnectionError('[sim] embedding server gone')
        S.sleep(0.15)
        return "Background information (use only if relevant):\n- " + ("manual text " * 92)

    def close(self):
        pass
