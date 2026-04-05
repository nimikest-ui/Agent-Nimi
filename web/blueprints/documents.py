"""Documents blueprint — upload, process, and manage knowledge base documents."""
import os
import tempfile
from flask import Blueprint, jsonify, request
from core.knowledge_base import (
    add_document, list_documents, delete_document,
    get_document, search as kb_search,
)

documents_bp = Blueprint("documents", __name__, url_prefix="/api/documents")

# Max upload size: 20 MB
MAX_UPLOAD_BYTES = 20 * 1024 * 1024

ALLOWED_EXTENSIONS = {
    ".txt", ".md", ".pdf", ".docx", ".csv", ".json", ".yaml", ".yml",
    ".xml", ".html", ".htm", ".py", ".js", ".sh", ".conf", ".cfg",
    ".ini", ".toml", ".log", ".rst", ".tex", ".c", ".h", ".cpp",
    ".java", ".rb", ".go", ".rs", ".sql",
}


def _allowed(filename: str) -> bool:
    ext = os.path.splitext(filename)[1].lower()
    return ext in ALLOWED_EXTENSIONS


@documents_bp.route("", methods=["GET"])
def get_documents():
    """List all documents in the knowledge base."""
    docs = list_documents()
    return jsonify({"documents": docs, "count": len(docs)})


@documents_bp.route("/upload", methods=["POST"])
def upload_document():
    """Upload and process a document into the knowledge base."""
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "Empty filename"}), 400

    if not _allowed(file.filename):
        return jsonify({"error": f"Unsupported file type. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"}), 400

    # Read into temp file
    data = file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        return jsonify({"error": f"File too large. Max {MAX_UPLOAD_BYTES // (1024*1024)} MB"}), 400

    tags = request.form.getlist("tags")

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as tmp:
            tmp.write(data)
            tmp_path = tmp.name

        doc = add_document(tmp_path, file.filename, tags=tags)
        return jsonify({"success": True, "document": doc})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"Processing failed: {e}"}), 500
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


@documents_bp.route("/<doc_id>", methods=["DELETE"])
def remove_document(doc_id: str):
    """Delete a document from the knowledge base."""
    if delete_document(doc_id):
        return jsonify({"success": True})
    return jsonify({"error": "Document not found"}), 404


@documents_bp.route("/<doc_id>", methods=["GET"])
def get_doc(doc_id: str):
    """Get metadata for a single document."""
    doc = get_document(doc_id)
    if doc:
        return jsonify(doc)
    return jsonify({"error": "Document not found"}), 404


@documents_bp.route("/search", methods=["POST"])
def search_documents():
    """Search the knowledge base."""
    data = request.get_json() or {}
    query = data.get("query", "").strip()
    if not query:
        return jsonify({"error": "Query required"}), 400
    max_chunks = min(int(data.get("max_chunks", 5)), 20)
    results = kb_search(query, max_chunks=max_chunks)
    return jsonify({"results": results, "count": len(results)})
