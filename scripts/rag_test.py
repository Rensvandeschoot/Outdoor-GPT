"""Quick retrieval sanity check on a built index.

Shows which chunks the retriever finds for a few test questions, without
running the full voice agent. The embedding server must be running
(start_embedding_server.ps1 on Windows, start_embedding_server.sh on the Pi).

Usage:
    python scripts/rag_test.py                          # built-in test questions
    python scripts/rag_test.py "How do I treat a burn?" # your own question(s)
"""

import argparse

from rag import RagRetriever

DEFAULT_QUERIES = [
    "How do I purify water so it is safe to drink?",
    "What can I cook over a campfire with just potatoes and bacon?",
    "How do I build a shelter to stay warm at night?",
    "How do I treat a snake bite?",
    "What is the capital of France?",  # off-topic control: should find nothing
]


def main():
    parser = argparse.ArgumentParser(description="Retrieval sanity check.")
    parser.add_argument("queries", nargs="*", default=None, help="Questions to test (default: a built-in set incl. an off-topic control).")
    parser.add_argument("--index_dir", default="rag_index", help="Index directory built by rag_ingest.py.")
    parser.add_argument("--embedding_server_url", default="http://localhost:8081/v1", help="OpenAI-compatible embedding server url.")
    parser.add_argument("--top_k", type=int, default=2, help="Chunks to show per question.")
    parser.add_argument("--min_score", type=float, default=0.35, help="Minimum cosine similarity.")
    args = parser.parse_args()

    retriever = RagRetriever(args.index_dir, args.embedding_server_url,
                             top_k=args.top_k, min_score=args.min_score)
    print(f"index: {len(retriever.chunks)} chunks, "
          f"{retriever.embeddings.shape[1]} dimensions")

    for query in (args.queries or DEFAULT_QUERIES):
        print(f"\nQ: {query}")
        results = retriever.retrieve(query)
        if not results:
            print("   (no match above threshold - the model answers on its own)")
        for score, chunk in results:
            source = chunk["source"].replace("\\", "/").split("/")[-1]
            print(f"   {score:.3f} [{source}] {chunk['text'][:100]}...")

    retriever.close()


if __name__ == "__main__":
    main()
