"""
ingestion/ingest.py — Main ingestion pipeline.

Usage:
    python -m ingestion.ingest --pdf-dir ../pdfs
    python -m ingestion.ingest --pdf-dir ../pdfs --force CEF_SOP.pdf
    python -m ingestion.ingest --pdf-dir ../pdfs --debug
    python -m ingestion.ingest --status

The pipeline:
  1. Scan --pdf-dir for .pdf files
  2. For each PDF, check the manifest (skip if hash matches → no duplicate ingestion)
  3. Extract text page-by-page with pdfplumber
  4. Clean header/footer noise from each page
  5. Detect document type → select chunking strategy
  6. Chunk the document
  7. Embed chunks with sentence-transformers
  8. Store in ChromaDB (persistent)
  9. Update manifest
"""

import argparse
import re
import sys
from pathlib import Path
from typing import List

import pdfplumber
import chromadb
from sentence_transformers import SentenceTransformer

# Allow running as `python -m ingestion.ingest` from backend/
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import (
    CHROMA_DB_PATH,
    CHROMA_COLLECTION,
    EMBEDDING_MODEL,
    detect_document_type,
)
from ingestion.manifest import (
    is_already_ingested,
    mark_as_ingested,
    remove_from_manifest,
    get_ingestion_status,
)
from ingestion.chunkers import get_chunker


# ─────────────────────────────────────────────────────────────────────────────
# Header / footer noise removal
# ─────────────────────────────────────────────────────────────────────────────

def clean_page_text(text: str) -> str:
    """
    Remove common PDF header/footer noise found in FEMA documents.
    Handles:
      - "Page 6 of 7" / "P age 6 of 7"  (pdfplumber OCR spacing artifacts)
      - "Public Assistance Division"  footer lines
      - Standalone page numbers like "6" or "- 6 -"
      - "FOR OFFICIAL USE ONLY" / document classification banners
    """
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        # Remove common page header/footer artifacts even when embedded inside other text.
        line = re.sub(r"P\s*age\s+\d+\s+of\s+\d+", "", line, flags=re.I)
        line = re.sub(r"Page\s+\d+\s+of\s+\d+", "", line, flags=re.I)

        stripped = line.strip()

        # Skip blank lines that are just whitespace
        if not stripped:
            continue

        # Full-line page artifacts (kept as a safeguard)
        if re.match(r'^P\s*age\s+\d+\s+of\s+\d+$', stripped, re.I):
            continue
        if re.match(r'^Page\s+\d+\s+of\s+\d+$', stripped, re.I):
            continue

        # "- 6 -" style page numbers
        if re.match(r'^-\s*\d+\s*-$', stripped):
            continue

        # Standalone page numbers: "6", "12" (max 3 digits, alone on line)
        if re.match(r'^\d{1,3}$', stripped):
            continue

        # FEMA division/office footer lines
        # e.g. "Public Assistance Division", "Federal Emergency Management Agency"
        if re.match(
            r'^(Public Assistance|Federal Emergency Management|FEMA)'
            r'.{0,50}(Division|Agency|Office|Branch|Program)$',
            stripped, re.I
        ):
            continue

        # Document classification / handling banners
        if re.match(
            r'^(FOR OFFICIAL USE ONLY|FOUO|UNCLASSIFIED|DRAFT)$',
            stripped, re.I
        ):
            continue

        cleaned.append(line)

    return "\n".join(cleaned)


# ─────────────────────────────────────────────────────────────────────────────
# PDF extraction
# ─────────────────────────────────────────────────────────────────────────────


def _table_to_markdown(table: list) -> str:
    """Convert a pdfplumber table (list of rows) to GitHub-flavored markdown."""
    if not table:
        return ""
    rows: List[List[str]] = []
    for row in table:
        cells = [
            str(c).strip().replace("\n", " ").replace("|", "\\|") if c is not None else ""
            for c in row
        ]
        rows.append(cells)
    if not any(any(c for c in r) for r in rows):
        return ""
    width = max(len(r) for r in rows)
    norm = [r + [""] * (width - len(r)) for r in rows]
    header = norm[0]
    sep = "|" + "|".join(["---"] * width) + "|"
    lines = ["| " + " | ".join(header) + " |", sep]
    for r in norm[1:]:
        lines.append("| " + " | ".join(r) + " |")
    return "\n".join(lines)


def _append_page_tables(page, base_text: str) -> str:
    """
    Append structured tables detected on the page as markdown blocks.
    Improves RAG on SOP/policy tables vs. noisy single-column extract_text only.
    """
    tables = []
    try:
        tables = page.extract_tables(
            {
                "vertical_strategy": "lines",
                "horizontal_strategy": "lines",
                "intersection_tolerance": 5,
                "snap_tolerance": 3,
                "join_tolerance": 3,
            }
        ) or []
    except Exception:
        try:
            tables = page.extract_tables() or []
        except Exception:
            tables = []
    if not tables:
        return base_text
    parts = [base_text]
    for ti, table in enumerate(tables, start=1):
        md = _table_to_markdown(table)
        if md:
            parts.append(f"\n\n### Table on page (extracted)\n{md}\n")
    return "".join(parts)


def extract_pages(pdf_path: Path) -> List[tuple[int, str]]:
    """
    Extract (page_number, text) tuples from a PDF using pdfplumber.
    Each page's text is cleaned to remove header/footer noise before returning.
    Uses extract_text plus extract_tables (as markdown) when table lines exist.
    """
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text(x_tolerance=2, y_tolerance=2) or ""
            text = clean_page_text(text.strip())
            text = _append_page_tables(page, text).strip()
            pages.append((i, text))
    # Filter out pages that are empty after cleaning
    return [(pn, t) for pn, t in pages if t]


# ─────────────────────────────────────────────────────────────────────────────
# ChromaDB setup
# ─────────────────────────────────────────────────────────────────────────────

def get_chroma_collection():
    client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
    # get_or_create so we can ingest incrementally across runs
    collection = client.get_or_create_collection(
        name=CHROMA_COLLECTION,
        metadata={"hnsw:space": "cosine"},  # use cosine similarity
    )
    return collection


# ─────────────────────────────────────────────────────────────────────────────
# Core ingestion function
# ─────────────────────────────────────────────────────────────────────────────

def ingest_pdf(
    pdf_path: Path,
    collection,
    embedder: SentenceTransformer,
    debug: bool = False,
) -> int:
    """
    Ingest a single PDF. Returns the number of chunks stored.
    """
    filename = pdf_path.name
    doc_label, chunker_name = detect_document_type(filename)

    print(f"\n[ingest] {filename}")
    print(f"         Document type : {doc_label}")
    print(f"         Chunker       : {chunker_name}")

    # 1. Extract text
    pages = extract_pages(pdf_path)
    print(f"         Pages extracted: {len(pages)}")

    if not pages:
        print(f"[warn]   No text extracted from {filename}. Skipping.")
        return 0

    # 2. Chunk
    chunker = get_chunker(chunker_name)
    chunks = chunker.chunk(pages, filename)
    print(f"         Chunks produced: {len(chunks)}")

    if debug:
        print("\n--- First 2 chunks (debug) ---")
        for c in chunks[:2]:
            print(f"  [page {c['page_number']}] [{c['section'][:50]}]")
            print(f"  {c['text'][:200]}")
            print()

    if not chunks:
        print(f"[warn]   No chunks produced for {filename}. Skipping.")
        return 0

    # 3. Embed
    texts = [c["text"] for c in chunks]
    embeddings = embedder.encode(texts, show_progress_bar=True, batch_size=32)

    # 4. Store in ChromaDB
    #    IDs are deterministic: filename + chunk_index (so re-ingestion is safe with upsert)
    ids = [f"{filename}__chunk_{c['chunk_index']:05d}" for c in chunks]
    metadatas = [
        {
            "source_document": filename,
            "document_label": doc_label,
            "page_number": c["page_number"],
            "section": c["section"],
            "section_path": c.get("section_path") or c["section"],
            "chunk_index": c["chunk_index"],
            "chunk_strategy": c["chunk_strategy"],
        }
        for c in chunks
    ]

    # Use add (not upsert) — but since we check manifest first, duplicates don't happen.
    # Use upsert defensively in case someone force-reingestd.
    collection.upsert(
        ids=ids,
        documents=texts,
        embeddings=embeddings.tolist(),
        metadatas=metadatas,
    )

    print(f"[chroma] Stored {len(chunks)} chunks OK")
    return len(chunks)


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Ingest FEMA PDFs into ChromaDB")
    parser.add_argument("--pdf-dir", type=Path, default=Path("../pdfs"),
                        help="Directory containing FEMA PDF files")
    parser.add_argument("--force", nargs="*", metavar="FILENAME",
                        help="Force re-ingest specific files (by filename). "
                             "Pass no filenames to force ALL.")
    parser.add_argument("--debug", action="store_true",
                        help="Print chunk previews during ingestion")
    parser.add_argument("--status", action="store_true",
                        help="Print ingestion manifest and exit")
    args = parser.parse_args()

    if args.status:
        status = get_ingestion_status()
        if not status:
            print("No files ingested yet.")
        else:
            print(f"\nIngestion manifest ({len(status)} files):")
            for fname, info in status.items():
                print(f"  {fname}")
                print(f"    chunks     : {info['num_chunks']}")
                print(f"    chunker    : {info['chunker']}")
                print(f"    ingested at: {info['ingested_at']}")
        return

    pdf_dir = args.pdf_dir.resolve()
    if not pdf_dir.exists():
        print(f"[error] PDF directory not found: {pdf_dir}")
        sys.exit(1)

    pdf_files = sorted(pdf_dir.glob("*.pdf"))
    if not pdf_files:
        print(f"[error] No PDF files found in {pdf_dir}")
        sys.exit(1)

    print(f"Found {len(pdf_files)} PDF(s) in {pdf_dir}")

    # Handle --force: remove specified files from manifest
    if args.force is not None:
        if len(args.force) == 0:
            # Force ALL
            for pdf in pdf_files:
                remove_from_manifest(pdf.name)
                print(f"[manifest] Cleared manifest entry for {pdf.name}")
        else:
            for fname in args.force:
                if remove_from_manifest(fname):
                    print(f"[manifest] Cleared manifest entry for {fname}")
                else:
                    print(f"[manifest] {fname} was not in manifest")

    # Load model and collection once
    print(f"\nLoading embedding model: {EMBEDDING_MODEL} ...")
    embedder = SentenceTransformer(EMBEDDING_MODEL)

    print("Connecting to ChromaDB ...")
    collection = get_chroma_collection()

    total_new = 0
    skipped = 0

    for pdf_path in pdf_files:
        if is_already_ingested(pdf_path):
            print(f"[manifest] {pdf_path.name} -> ALREADY INGESTED (hash match) - skipping")
            skipped += 1
            continue

        print(f"[manifest] {pdf_path.name} -> NEW or MODIFIED - ingesting ...")
        n = ingest_pdf(pdf_path, collection, embedder, debug=args.debug)

        if n > 0:
            doc_label, chunker_name = detect_document_type(pdf_path.name)
            mark_as_ingested(pdf_path, doc_label, chunker_name, n)
            total_new += n

    print(f"\n{'-'*50}")
    print(f"Ingestion complete.")
    print(f"  New chunks stored : {total_new}")
    print(f"  Files skipped     : {skipped}")
    print(f"  Total in DB       : {collection.count()}")


if __name__ == "__main__":
    main()