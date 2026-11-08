"""Fake RagRetriever: index load time, then the real wait (voice_agent_utils.wait_for_server)."""
import simworld as S
import voice_agent_utils


class RagRetriever:
    def __init__(self, index_dir, embedding_server_url, top_k=2, min_score=0.35, max_context_chars=1200,
                 server_pid=None, server_wait=voice_agent_utils.SERVER_WAIT_CEILING):
        S.sleep(S.W.jit(1.5, 'rag_load'))
        self.chunks = [None] * 8082

        def ping():
            S.sleep(0.02)
            return S.W.embed_ready()
        voice_agent_utils.wait_for_server(ping, f"embedding server at {embedding_server_url}",
                                          pid=server_pid, ceiling=server_wait)

    def get_context(self, query):
        if not S.W.embed_ready():
            raise ConnectionError('[sim] embedding server gone')
        S.sleep(0.15)
        return "Background information (use only if relevant):\n- " + ("manual text " * 92)

    def close(self):
        pass
