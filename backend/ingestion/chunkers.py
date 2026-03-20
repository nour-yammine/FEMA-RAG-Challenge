"""
ingestion/chunkers.py — Document-specific chunking strategies.

Each chunker takes a list of (page_number, page_text) tuples extracted from a PDF
and returns a list of chunk dicts ready for storage in ChromaDB.

Chunk dict schema:
{
    "text":            str,   # the chunk text
    "page_number":     int,   # page where the chunk starts
    "section":         str,   # detected section/header title (best effort)
    "section_path":    str,   # breadcrumb: "Ch 2 > 2.1 Overview" (hierarchy)
    "chunk_index":     int,   # sequential index within this document
    "chunk_strategy":  str,    # name of the chunker class used
}
"""

from __future__ import annotations

import re
from typing import List, Tuple, Optional


PagedText = List[Tuple[int, str]]   # [(page_number, text), ...]


# ─────────────────────────────────────────────────────────────────────────────
# Base helpers
# ─────────────────────────────────────────────────────────────────────────────

def _split_by_chars(text: str, chunk_size: int, overlap: int) -> List[str]:
    """
    Character-level sliding window splitter that respects sentence boundaries.

    Priority for break point (best → fallback):
      1. Sentence boundary (. ! ?) in the last 20% of the chunk window
      2. Newline
      3. Space
      4. Hard cut at chunk_size

    This prevents chunks from being cut mid-sentence, which was causing
    truncated context like "g improved and alternate projects) is calculated by dividing the".
    """
    if len(text) <= chunk_size:
        return [text.strip()]

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        if end >= len(text):
            chunks.append(text[start:].strip())
            break

        # 1. Try sentence boundary in the last 20% of the window
        search_from = start + int(chunk_size * 0.8)
        break_at = -1
        for punct in '.!?':
            pos = text.rfind(punct, search_from, end)
            if pos > break_at:
                break_at = pos

        if break_at > start:
            # Include the punctuation itself
            break_at += 1
        else:
            # 2. Fall back to newline
            break_at = text.rfind("\n", start, end)
            if break_at <= start:
                # 3. Fall back to space
                break_at = text.rfind(" ", start, end)
            if break_at <= start:
                # 4. Hard cut
                break_at = end

        chunk_text = text[start:break_at].strip()
        if chunk_text:
            chunks.append(chunk_text)

        # Next window starts with overlap, but avoid starting mid-word.
        next_start = break_at - overlap
        if next_start <= start:
            next_start = break_at  # ensure forward progress

        if next_start > 0:
            # Backtrack to a nearby whitespace/newline within a short range.
            back = text.rfind("\n", next_start, break_at)
            if back == -1:
                back = text.rfind(" ", next_start, break_at)
            if back != -1:
                # If we found whitespace close enough, start right after it.
                if back >= next_start - 60:
                    next_start = back + 1

        start = next_start

    return [c for c in chunks if c]


def _heading_outline_depth(line: str) -> int:
    """
    Numeric depth for hierarchy stacking (1 = top-level chapter/section).
    Larger depth = nested. Non-outline headers get depth 6.
    """
    stripped = line.strip()
    m = re.match(r"^(\d+(?:\.\d+)*)[\s.)]", stripped)
    if m:
        return len(m.group(1).split("."))
    m = re.match(r"(?i)^(chapter|section|part|appendix)\s+(\d+|[IVXLC]+)\b", stripped)
    if m:
        return 1
    if _detect_section_header(stripped):
        return 6
    return 6


def _update_section_stack(stack: List[Tuple[int, str]], line: str) -> str:
    """Push/pop outline stack from a new heading line; return breadcrumb path."""
    title = line.strip()
    depth = _heading_outline_depth(line)
    while stack and stack[-1][0] >= depth:
        stack.pop()
    stack.append((depth, title))
    return " > ".join(t[1] for t in stack)


def _detect_section_header(line: str) -> bool:
    """
    Heuristic to detect whether a line is a section header in FEMA docs.
    Matches patterns like:
      "Chapter 2", "CHAPTER 2", "A. Applicant Eligibility",
      "2.1 Overview", "I. Introduction", "Section 1:"
    """
    patterns = [
        r"^(chapter|section|part|appendix)\s+\d+",
        r"^[A-Z][A-Z\s]{3,}$",                         # ALL CAPS heading
        r"^\d+(\.\d+)*\s+[A-Z]",                        # "2.1 Title"
        r"^[IVXLC]+\.\s+[A-Z]",                         # "IV. Title"
        r"^[A-Z]\.\s+[A-Z][a-zA-Z\s]+$",                # "A. Title"
    ]
    stripped = line.strip()
    if not stripped or len(stripped) > 120:
        return False
    for pat in patterns:
        if re.match(pat, stripped, re.IGNORECASE):
            return True
    return False


def _build_full_text(pages: PagedText) -> str:
    """Concatenate all pages into a single string."""
    return "\n".join(text for _, text in pages)


def _make_chunk(
    text: str,
    page: int,
    section: str,
    index: int,
    strategy: str,
    section_path: Optional[str] = None,
) -> dict:
    path = (section_path or "").strip() or section
    return {
        "text": text.strip(),
        "page_number": page,
        "section": section,
        "section_path": path,
        "chunk_index": index,
        "chunk_strategy": strategy,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 1. HierarchicalChunker — for PAPPG (329-page policy guide)
#
#    Strategy:
#    - Walk through pages, detect section headers
#    - Accumulate text under each section header
#    - When a section gets large, split it with char-level splitter
#    - Prepend the section title to every chunk for self-contained retrieval
# ─────────────────────────────────────────────────────────────────────────────

class HierarchicalChunker:
    """
    For the PAPPG — 329-page deeply nested policy guide.
    Splits first by section boundaries, then by character count within sections.
    Section header is prepended to each sub-chunk so every chunk is context-rich.
    """

    CHUNK_SIZE = 1200
    OVERLAP = 200
    STRATEGY = "HierarchicalChunker"

    def chunk(self, pages: PagedText, source_document: str) -> List[dict]:
        chunks: List[dict] = []
        current_section = "Introduction"
        current_section_page = 1
        current_text: List[str] = []
        section_stack: List[Tuple[int, str]] = []
        current_path = "Introduction"
        index = 0

        def flush(section, section_path: str, page, text_lines):
            nonlocal index
            combined = "\n".join(text_lines).strip()
            if not combined:
                return
            # Prepend section header + breadcrumb for self-contained retrieval
            prefix = f"[Section path: {section_path}]\n[Section: {section}]\n\n"
            sub_chunks = _split_by_chars(combined, self.CHUNK_SIZE, self.OVERLAP)
            for sc in sub_chunks:
                chunks.append(
                    _make_chunk(prefix + sc, page, section, index, self.STRATEGY, section_path),
                )
                index += 1

        for page_num, page_text in pages:
            lines = page_text.split("\n")
            for line in lines:
                if _detect_section_header(line):
                    flush(current_section, current_path, current_section_page, current_text)
                    current_path = _update_section_stack(section_stack, line)
                    current_section = line.strip()
                    current_section_page = page_num
                    current_text = []
                else:
                    current_text.append(line)

        flush(current_section, current_path, current_section_page, current_text)
        return chunks


# ─────────────────────────────────────────────────────────────────────────────
# 2. ProceduralChunker — for CEF SOP and SFM SOP (6–7 page dense SOPs)
#
#    Strategy:
#    - Detect numbered steps (1., Step 1:, a., etc.)
#    - Keep complete steps together — never split mid-step
#    - Merge very short steps with the next one
#    - Fall back to char-level splitting only if a single step is huge
# ─────────────────────────────────────────────────────────────────────────────

class ProceduralChunker:
    """
    For CEF SOP and SFM SOP — short, dense procedural documents.
    Preserves numbered steps intact; never cuts a step in half.
    """

    CHUNK_SIZE = 800
    OVERLAP = 150
    MIN_STEP_CHARS = 80    # Steps shorter than this are merged with the next
    STRATEGY = "ProceduralChunker"

    # Patterns that mark the START of a new procedural step
    STEP_PATTERNS = [
        re.compile(r"^\s*(\d+)\.\s+\S"),          # "1. Do something"
        re.compile(r"^\s*Step\s+\d+", re.I),       # "Step 1:"
        re.compile(r"^\s*[a-z]\.\s+\S"),           # "a. sub-step"
        re.compile(r"^\s*[A-Z]\.\s+\S"),           # "A. Sub-step"
        re.compile(r"^\s*•\s+\S"),                  # Bullet
    ]

    def _is_step_start(self, line: str) -> bool:
        return any(p.match(line) for p in self.STEP_PATTERNS)

    def _extract_section_label(self, text: str) -> str:
        # Prefer actual step/bullet starts inside the chunk; chunks may begin mid-word.
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if self._is_step_start(stripped):
                return stripped[:80]

        # Fallback: first non-empty line (may still be mid-word if chunk starts inside a step).
        for line in text.splitlines():
            stripped = line.strip()
            if stripped:
                return stripped[:80]
        return "Procedural Step"

    def chunk(self, pages: PagedText, source_document: str) -> List[dict]:
        full_text = _build_full_text(pages)
        lines = full_text.split("\n")

        steps: List[str] = []
        current_step: List[str] = []

        for line in lines:
            if self._is_step_start(line) and current_step:
                steps.append("\n".join(current_step).strip())
                current_step = [line]
            else:
                current_step.append(line)
        if current_step:
            steps.append("\n".join(current_step).strip())

        merged: List[str] = []
        buffer = ""
        for step in steps:
            if not step:
                continue
            candidate = (buffer + "\n\n" + step).strip() if buffer else step
            if len(candidate) <= self.CHUNK_SIZE:
                buffer = candidate
            else:
                if buffer:
                    merged.append(buffer)
                if len(step) > self.CHUNK_SIZE:
                    for sub in _split_by_chars(step, self.CHUNK_SIZE, self.OVERLAP):
                        merged.append(sub)
                    buffer = ""
                else:
                    buffer = step
        if buffer:
            merged.append(buffer)

        # Page assignment: find each chunk in a page's text
        def find_page_for_chunk(chunk_text: str) -> int:
            snippet = chunk_text[:60].strip()
            for pn, pt in pages:
                if snippet in pt:
                    return pn
            return pages[0][0] if pages else 1

        chunks = []
        for i, text in enumerate(merged):
            page = find_page_for_chunk(text)
            section = self._extract_section_label(text)
            path = f"Procedure > {section}"
            chunks.append(
                _make_chunk(
                    f"[Procedure / step context: {section[:100]}]\n\n{text}",
                    page,
                    section,
                    i,
                    self.STRATEGY,
                    path,
                ),
            )
        return chunks


# ─────────────────────────────────────────────────────────────────────────────
# 3. SectionChunker — for Damage Assessment Manual (128 pages)
#
#    Strategy:
#    - Mid-size document with clear section structure
#    - Track page number per chunk
#    - Split at section boundaries first, then by char count within sections
#    - Slightly larger chunk size to preserve procedural paragraphs
# ─────────────────────────────────────────────────────────────────────────────

class SectionChunker:
    """
    For the Damage Assessment Manual (128 pages).
    Similar to HierarchicalChunker but simpler — no deep nesting assumed.
    Uses page-aware splitting with section labels.
    """

    CHUNK_SIZE = 1000
    OVERLAP = 200
    STRATEGY = "SectionChunker"

    def chunk(self, pages: PagedText, source_document: str) -> List[dict]:
        chunks: List[dict] = []
        current_section = "General"
        current_page = pages[0][0] if pages else 1
        section_stack: List[Tuple[int, str]] = []
        current_path = "General"
        buffer: List[str] = []
        index = 0

        def flush():
            nonlocal index
            text = "\n".join(buffer).strip()
            if not text:
                return
            prefix = f"[Section path: {current_path}]\n\n"
            for sub in _split_by_chars(text, self.CHUNK_SIZE, self.OVERLAP):
                chunks.append(
                    _make_chunk(
                        prefix + sub,
                        current_page,
                        current_section,
                        index,
                        self.STRATEGY,
                        current_path,
                    ),
                )
                index += 1

        for page_num, page_text in pages:
            for line in page_text.split("\n"):
                if _detect_section_header(line):
                    flush()
                    buffer.clear()
                    current_path = _update_section_stack(section_stack, line)
                    current_section = line.strip()
                    current_page = page_num
                else:
                    buffer.append(line)

        flush()
        return chunks


# ─────────────────────────────────────────────────────────────────────────────
# 4. MixedChunker — for PA Applicant Handbook (134 pages)
#
#    Strategy:
#    - Paragraph-aware splitting (double newline = paragraph boundary)
#    - Section headers are detected and prepended
#    - Moderate chunk size with overlap
#    - Good for narrative/guide-style documents
# ─────────────────────────────────────────────────────────────────────────────

class MixedChunker:
    """
    For the PA Applicant Handbook (134 pages) and unknown documents.
    Paragraph-aware: splits on double newlines first, then by character count.
    """

    CHUNK_SIZE = 1000
    OVERLAP = 150
    STRATEGY = "MixedChunker"

    def chunk(self, pages: PagedText, source_document: str) -> List[dict]:
        chunks: List[dict] = []
        index = 0
        current_section = "General"
        section_stack: List[Tuple[int, str]] = []
        current_path = "General"

        def emit_block(raw: str, page_num: int) -> None:
            nonlocal index
            if not raw.strip():
                return
            prefix = f"[Section path: {current_path}]\n\n"
            for sub in _split_by_chars(raw, self.CHUNK_SIZE, self.OVERLAP):
                chunks.append(
                    _make_chunk(
                        prefix + sub,
                        page_num,
                        current_section,
                        index,
                        self.STRATEGY,
                        current_path,
                    ),
                )
                index += 1

        for page_num, page_text in pages:
            paragraphs = re.split(r"\n{2,}", page_text)
            buffer = ""

            for para in paragraphs:
                para = para.strip()
                if not para:
                    continue

                first_line = para.split("\n")[0]
                if _detect_section_header(first_line):
                    if buffer.strip():
                        emit_block(buffer, page_num)
                    buffer = ""
                    current_path = _update_section_stack(section_stack, first_line)
                    current_section = first_line.strip()

                candidate = (buffer + "\n\n" + para).strip() if buffer else para
                if len(candidate) > self.CHUNK_SIZE:
                    if buffer.strip():
                        emit_block(buffer, page_num)
                    buffer = para
                else:
                    buffer = candidate

            if buffer.strip():
                emit_block(buffer, page_num)
                buffer = ""

        return chunks


# ─────────────────────────────────────────────────────────────────────────────
# Factory
# ─────────────────────────────────────────────────────────────────────────────

CHUNKER_REGISTRY = {
    "HierarchicalChunker": HierarchicalChunker,
    "ProceduralChunker":   ProceduralChunker,
    "SectionChunker":      SectionChunker,
    "MixedChunker":        MixedChunker,
}


def get_chunker(chunker_name: str):
    """Return an instantiated chunker by name."""
    cls = CHUNKER_REGISTRY.get(chunker_name, MixedChunker)
    return cls()