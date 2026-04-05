"""
Knowledge Base — persistent document store for Agent-Nimi.

Documents are uploaded, chunked, and stored as searchable text.
The agent can query the KB at inference time to augment its context.
"""
import hashlib
import json
import re
import time
from pathlib import Path

KB_DIR = Path.home() / ".agent-nimi" / "knowledge"
KB_INDEX = KB_DIR / "index.json"
CHUNKS_DIR = KB_DIR / "chunks"

# ── Chunking config ──────────────────────────────────────────────────────────
CHUNK_SIZE = 1200      # characters per chunk
CHUNK_OVERLAP = 200    # overlap between consecutive chunks


def _ensure_dirs():
    KB_DIR.mkdir(parents=True, exist_ok=True)
    CHUNKS_DIR.mkdir(parents=True, exist_ok=True)


def _load_index() -> dict:
    _ensure_dirs()
    if KB_INDEX.exists():
        return json.loads(KB_INDEX.read_text())
    return {"documents": []}


def _save_index(index: dict):
    _ensure_dirs()
    KB_INDEX.write_text(json.dumps(index, indent=2))


# ── Document processing ─────────────────────────────────────────────────────

def extract_text(file_path: str, filename: str) -> str:
    """Extract plain text from a file based on its extension."""
    ext = Path(filename).suffix.lower()
    path = Path(file_path)

    if ext == ".pdf":
        return _extract_pdf(path)
    elif ext in (".docx",):
        return _extract_docx(path)
    elif ext in (".md", ".txt", ".log", ".csv", ".json", ".yaml", ".yml",
                  ".xml", ".html", ".htm", ".py", ".js", ".sh", ".conf",
                  ".cfg", ".ini", ".toml", ".rst", ".tex", ".c", ".h",
                  ".cpp", ".java", ".rb", ".go", ".rs", ".sql"):
        return _extract_text(path)
    else:
        # Try as plain text
        return _extract_text(path)


def _extract_pdf(path: Path) -> str:
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(str(path))
        pages = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
        return "\n\n".join(pages)
    except Exception as e:
        raise ValueError(f"Failed to extract PDF: {e}")


def _extract_docx(path: Path) -> str:
    try:
        from docx import Document
        doc = Document(str(path))
        return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except Exception as e:
        raise ValueError(f"Failed to extract DOCX: {e}")


def _extract_text(path: Path) -> str:
    try:
        import chardet
        raw = path.read_bytes()
        detected = chardet.detect(raw)
        encoding = detected.get("encoding") or "utf-8"
        return raw.decode(encoding, errors="replace")
    except Exception:
        return path.read_text(errors="replace")


# ── Chunking ────────────────────────────────────────────────────────────────

def chunk_text(text: str, chunk_size: int = CHUNK_SIZE,
               overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping chunks for retrieval."""
    # Normalize whitespace
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    if not text:
        return []

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        # Try to break at a sentence or paragraph boundary
        if end < len(text):
            # Look for last paragraph break
            last_para = chunk.rfind('\n\n')
            if last_para > chunk_size * 0.3:
                end = start + last_para + 2
                chunk = text[start:end]
            else:
                # Look for last sentence end
                last_sent = max(chunk.rfind('. '), chunk.rfind('.\n'),
                                chunk.rfind('? '), chunk.rfind('! '))
                if last_sent > chunk_size * 0.3:
                    end = start + last_sent + 1
                    chunk = text[start:end]
        chunks.append(chunk.strip())
        start = end - overlap if end < len(text) else end
    return [c for c in chunks if c]


# ── CRUD operations ─────────────────────────────────────────────────────────

def add_document(file_path: str, filename: str, tags: list[str] = None) -> dict:
    """Process a document and add it to the knowledge base.

    Returns the document metadata dict.
    """
    _ensure_dirs()
    text = extract_text(file_path, filename)
    if not text.strip():
        raise ValueError("No text could be extracted from the document.")

    chunks = chunk_text(text)
    doc_id = hashlib.sha256(f"{filename}:{time.time()}".encode()).hexdigest()[:12]

    # Save chunks
    chunk_dir = CHUNKS_DIR / doc_id
    chunk_dir.mkdir(parents=True, exist_ok=True)
    for i, chunk in enumerate(chunks):
        (chunk_dir / f"{i:04d}.txt").write_text(chunk)

    doc_meta = {
        "id": doc_id,
        "filename": filename,
        "tags": tags or [],
        "chunks": len(chunks),
        "chars": len(text),
        "added_at": time.time(),
    }

    index = _load_index()
    index["documents"].append(doc_meta)
    _save_index(index)
    return doc_meta


def list_documents() -> list[dict]:
    """Return all document metadata."""
    return _load_index().get("documents", [])


def delete_document(doc_id: str) -> bool:
    """Remove a document and its chunks."""
    import shutil
    index = _load_index()
    docs = index.get("documents", [])
    found = [d for d in docs if d["id"] == doc_id]
    if not found:
        return False
    index["documents"] = [d for d in docs if d["id"] != doc_id]
    _save_index(index)

    chunk_dir = CHUNKS_DIR / doc_id
    if chunk_dir.exists():
        shutil.rmtree(chunk_dir)
    return True


def get_document(doc_id: str) -> dict | None:
    """Get metadata for a single document."""
    for d in list_documents():
        if d["id"] == doc_id:
            return d
    return None


# ── Search / retrieval ───────────────────────────────────────────────────────

def search(query: str, max_chunks: int = 5) -> list[dict]:
    """Simple keyword search across all document chunks.

    Returns a list of {doc_id, filename, chunk_index, text, score}.
    """
    query_terms = set(query.lower().split())
    if not query_terms:
        return []

    results = []
    for doc in list_documents():
        chunk_dir = CHUNKS_DIR / doc["id"]
        if not chunk_dir.exists():
            continue
        for chunk_file in sorted(chunk_dir.glob("*.txt")):
            text = chunk_file.read_text()
            text_lower = text.lower()
            # Simple TF-based scoring
            score = sum(text_lower.count(term) for term in query_terms)
            if score > 0:
                results.append({
                    "doc_id": doc["id"],
                    "filename": doc["filename"],
                    "chunk_index": int(chunk_file.stem),
                    "text": text,
                    "score": score,
                })

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:max_chunks]


def get_context_for_prompt(query: str, max_chars: int = 3000) -> str:
    """Build a KB context block suitable for injecting into the system prompt."""
    hits = search(query, max_chunks=8)
    if not hits:
        return ""

    parts = []
    total = 0
    for hit in hits:
        text = hit["text"]
        if total + len(text) > max_chars:
            remaining = max_chars - total
            if remaining > 100:
                text = text[:remaining] + "…"
            else:
                break
        parts.append(f"[{hit['filename']}]\n{text}")
        total += len(text)

    if not parts:
        return ""

    return (
        "── Knowledge Base (uploaded documents) ──\n"
        + "\n---\n".join(parts)
        + "\n── End KB ──"
    )
