import json
import chromadb
import ollama
from pathlib import Path

EMBED_MODEL = "nomic-embed-text"
COLLECTION = "guitar_book"
ROOT = Path(__file__).resolve().parent.parent   # Guitar_Pro/ (one level above skeleton/)
DB_PATH = str(ROOT / "chroma_db")


def embed(texts, kind):
    """kind = 'document' or 'query'. nomic-embed-text expects a task prefix."""
    prefix = "search_document: " if kind == "document" else "search_query: "
    resp = ollama.embed(model=EMBED_MODEL, input=[prefix + t for t in texts],
                        options={"num_gpu": 0}, keep_alive="10m")
    return resp["embeddings"]

def get_collection():
    client = chromadb.PersistentClient(path=DB_PATH)
    return client.get_or_create_collection(COLLECTION, metadata={"hnsw:space": "cosine"})


def flatten_meta(c):
    return {
        "session": c["session"], "session_title": c["session_title"],
        "chunk_type": c["chunk_type"], "headings": " | ".join(c["headings"]),
        "pdf_page_start": c["pdf_page_start"], "pdf_page_end": c["pdf_page_end"],
        "printed_page_start": c["printed_page_start"], "printed_page_end": c["printed_page_end"],
        "has_notation": c["has_notation"],
    }


def build_index(chunks_path="chunks.json", batch=16):
    chunks = [c for c in json.load(open(chunks_path)) if c["embeddable"]]
    col = get_collection()
    for i in range(0, len(chunks), batch):
        part = chunks[i:i + batch]
        col.upsert(ids=[c["chunk_id"] for c in part],
                   documents=[c["text"] for c in part],
                   embeddings=embed([c["text"] for c in part], "document"),
                   metadatas=[flatten_meta(c) for c in part])
    print(f"Indexed {len(chunks)} chunks; collection now holds {col.count()}")


def search(question, k=4, where=None):
    col = get_collection()
    r = col.query(query_embeddings=embed([question], "query"), n_results=k, where=where)
    for cid, dist, meta in zip(r["ids"][0], r["distances"][0], r["metadatas"][0]):
        print(f"{dist:.3f}  {cid}  S{meta['session']} p{meta['printed_page_start']} "
              f"[{meta['chunk_type']}]  {meta['headings'][:60]}")
    return r


if __name__ == "__main__":
    build_index()

    