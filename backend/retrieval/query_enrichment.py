"""
query_enrichment.py — Acronym expansion and cross-reference follow-up queries
for retrieval. Improves recall on FEMA PA documents without a full citation graph.
"""
from __future__ import annotations

import re
from typing import List

from config import CROSS_REF_MAX_EXTRA_QUERIES, FEMA_ACRONYM_EXPANSIONS


def expand_query_for_embedding(question: str) -> str:
    """
    Append plain-language expansions for known acronyms so embeddings align
    with chunks that spell out the full term.
    """
    if not question.strip():
        return question
    extras: List[str] = []
    lower_blob = f" {question} "
    for acronym, expansion in FEMA_ACRONYM_EXPANSIONS.items():
        # Word-ish boundary: not preceded/followed by letters (handles "PA," "(CEF)")
        pat = rf"(?<![A-Za-z]){re.escape(acronym)}(?![A-Za-z])"
        if re.search(pat, question, flags=re.IGNORECASE):
            if expansion.lower() not in lower_blob:
                extras.append(expansion)
    if not extras:
        return question
    return question + " . " + " . ".join(extras)


def extract_followup_queries(question: str, chunk_snippets: List[str], max_queries: int) -> List[str]:
    """
    Mine the user question + top retrieved snippets for intra-document references
    (Chapter/Section/Appendix, forms) and build short auxiliary search queries.
    """
    if max_queries <= 0:
        return []
    blob = question + "\n" + "\n".join(s[:1200] for s in chunk_snippets if s)
    queries: List[str] = []
    seen: set[str] = set()

    def add(q: str) -> None:
        q = " ".join(q.split())
        if len(q) < 8 or len(q) > 220:
            return
        key = q.lower()
        if key in seen:
            return
        seen.add(key)
        queries.append(q)

    # "see Section 3.2 ...", "refer to Chapter IV ..."
    for m in re.finditer(
        r"(?i)(?:see|refer(?:\s+to)?|as\s+(?:described|discussed)\s+in)\s+"
        r"((?:Chapter|Section|Appendix|Part)\s+[^.\n]{1,100}(?:\.[^.\n]{0,40})?)",
        blob,
    ):
        add(m.group(1).strip())
        if len(queries) >= max_queries:
            return queries

    # Standalone Chapter/Section/Appendix references
    for m in re.finditer(
        r"(?i)\b((?:Appendix|Chapter|Section|Part)\s+[IVXLC\d]+(?:\.[\d]+)*(?:\s*[-–—]\s*[^\n.]{0,40})?)",
        blob,
    ):
        add(m.group(1).strip())
        if len(queries) >= max_queries:
            return queries

    # Form / FEMA / OMB style references
    for m in re.finditer(
        r"(?i)\b((?:FEMA|OMB)?\s*(?:Form|Std\.?)\s*[- ]?[A-Z]?\d{2,5}(?:\.\d+)?)\b",
        blob,
    ):
        add(m.group(1).strip())
        if len(queries) >= max_queries:
            return queries

    return queries[:max_queries]
