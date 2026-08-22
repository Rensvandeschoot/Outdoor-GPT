"""Build the RAG index from a folder of documents.

Reads .txt, .md and .pdf files (pdf requires: pip install pypdf), splits them
into overlapping chunks, embeds each chunk via the embedding server, and writes
the index (chunks.json + embeddings.npy) to the index directory.

The embedding server must be running first (see start_embedding_server.sh).
It does not have to run on this machine: you can build the index on a PC
while the embedding server runs on the Pi, as long as they share a network.

Usage:
    # embedding server on the same machine
    python rag_ingest.py --docs_dir docs

    # documents on a PC, embedding server on the Pi
    python rag_ingest.py --docs_dir docs --embedding_server_url http://<pi-ip>:8081/v1

The resulting index directory (rag_index/) is what needs to end up on the
device running the voice agent.
"""

import argparse
import json
import os
import sys

import numpy as np

from rag import embed_texts

TEXT_EXTENSIONS = {".txt", ".md"}


def extract_text(file_path):
    """Return plain text from a .txt/.md/.pdf file, or None if unsupported."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext in TEXT_EXTENSIONS:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    if ext == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            sys.exit("PDF support requires pypdf. Install with: pip install pypdf")
        reader = PdfReader(file_path)
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n".join(pages)
    return None


def chunk_text(text, chunk_words, overlap_words):
    """Split text into overlapping chunks of roughly chunk_words words."""
    words = text.split()
    if not words:
        return []
    chunks = []
    step = max(chunk_words - overlap_words, 1)
    for start in range(0, len(words), step):
        chunk = " ".join(words[start:start + chunk_words])
        if len(chunk.split()) >= 20:  # skip near-empty tail chunks
            chunks.append(chunk)
        if start + chunk_words >= len(words):
            break
    return chunks


def main():
    parser = argparse.ArgumentParser(description="Build RAG index from documents.")
    parser.add_argument("--docs_dir", required=True, help="Folder with .txt/.md/.pdf documents (searched recursively).")
    parser.add_argument("--index_dir", default="rag_index", help="Output folder for the index (default: rag_index).")
    parser.add_argument("--embedding_server_url", default="http://localhost:8081/v1", help="OpenAI-compatible embedding server (llama.cpp with --embedding). May point to another machine, e.g. http://<pi-ip>:8081/v1.")
    parser.add_argument("--chunk_words", type=int, default=150, help="Words per chunk (keep small: LLM context on the Pi is limited).")
    parser.add_argument("--overlap_words", type=int, default=30, help="Word overlap between consecutive chunks.")
    parser.add_argument("--batch_size", type=int, default=8, help="Chunks per embedding request.")
    args = parser.parse_args()

    # Collect chunks from all documents
    all_chunks = []
    n_files = 0
    for root, _dirs, files in os.walk(args.docs_dir):
        for filename in sorted(files):
            file_path = os.path.join(root, filename)
            text = extract_text(file_path)
            if text is None:
                continue
            source = os.path.relpath(file_path, args.docs_dir)
            chunks = chunk_text(text, args.chunk_words, args.overlap_words)
            if not chunks:
                print(f"  (no text found in {source}, skipping - scanned PDF? run OCR first, e.g. ocrmypdf)")
                continue
            n_files += 1
            print(f"  {source}: {len(chunks)} chunks")
            all_chunks.extend({"text": c, "source": source} for c in chunks)

    if not all_chunks:
        sys.exit(f"No usable documents found in '{args.docs_dir}' (.txt, .md, .pdf).")
    print(f"\n{n_files} documents -> {len(all_chunks)} chunks. Embedding...")

    # Embed in batches
    embeddings = []
    for i in range(0, len(all_chunks), args.batch_size):
        batch = [c["text"] for c in all_chunks[i:i + args.batch_size]]
        embeddings.append(embed_texts(batch, args.embedding_server_url))
        done = min(i + args.batch_size, len(all_chunks))
        print(f"  {done}/{len(all_chunks)}", end="\r")
    embeddings = np.vstack(embeddings)
    print()

    # Write index
    os.makedirs(args.index_dir, exist_ok=True)
    with open(os.path.join(args.index_dir, "chunks.json"), "w", encoding="utf-8") as f:
        json.dump(all_chunks, f, ensure_ascii=False, indent=1)
    np.save(os.path.join(args.index_dir, "embeddings.npy"), embeddings)

    size_mb = embeddings.nbytes / 1e6
    print(f"Index written to '{args.index_dir}' "
          f"({len(all_chunks)} chunks, embeddings {size_mb:.1f} MB).")
    print(f"Start the agent with: python voice_agent_cli.py --prompt_file prompts.json --rag_index {args.index_dir}")


if __name__ == "__main__":
    main()
