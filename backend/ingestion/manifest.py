"""
ingestion/manifest.py — tracks which PDFs have been ingested and their hashes.
Prevents duplicate ingestion when the pipeline is re-run.
"""
import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone

from config import MANIFEST_PATH


def load_manifest() -> dict:
    """Load the ingestion manifest from disk, or return an empty one."""
    if MANIFEST_PATH.exists():
        with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"ingested_files": {}}


def save_manifest(manifest: dict) -> None:
    """Persist the manifest to disk."""
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)


def get_file_hash(filepath: Path) -> str:
    """Compute MD5 hash of a file (streamed to handle large PDFs)."""
    hasher = hashlib.md5()
    with open(filepath, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            hasher.update(block)
    return hasher.hexdigest()


def is_already_ingested(filepath: Path) -> bool:
    """
    Returns True if this exact file (same name AND same MD5 hash) has
    already been ingested. A modified file (same name, different hash)
    returns False so it gets re-ingested.
    """
    manifest = load_manifest()
    name = filepath.name
    if name not in manifest["ingested_files"]:
        return False
    stored_hash = manifest["ingested_files"][name].get("hash", "")
    current_hash = get_file_hash(filepath)
    return stored_hash == current_hash


def mark_as_ingested(
    filepath: Path,
    document_label: str,
    chunker_name: str,
    num_chunks: int,
) -> None:
    """Record a successfully ingested file in the manifest."""
    manifest = load_manifest()
    manifest["ingested_files"][filepath.name] = {
        "hash": get_file_hash(filepath),
        "path": str(filepath.resolve()),
        "document_label": document_label,
        "chunker": chunker_name,
        "num_chunks": num_chunks,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
    }
    save_manifest(manifest)


def remove_from_manifest(filename: str) -> bool:
    """Remove a file from the manifest (forces re-ingestion). Returns True if found."""
    manifest = load_manifest()
    if filename in manifest["ingested_files"]:
        del manifest["ingested_files"][filename]
        save_manifest(manifest)
        return True
    return False


def get_ingestion_status() -> dict:
    """Return the full manifest as a summary dict for the API."""
    manifest = load_manifest()
    return manifest["ingested_files"]
