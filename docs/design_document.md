# Design Document: FEMA RAG Pipeline & Chat Application
**Candidate:** Nour Yammine  
**Assessment:** AI Department — RAG Pipeline & Chat Application

---

## 1. Architecture Overview

```
User (React UI)
    │  HTTP (fetch)
    ▼
FastAPI (main.py)
    ├── POST /chat ─── Retriever ──► ChromaDB (cosine similarity)
    │                 Generator ──► Azure OpenAI (GPT-3.5-Turbo)
    └── GET /ingestion-status ──► manifest.json

Ingestion Pipeline (offline, CLI)
    pdfs/ ──► pdfplumber ──► [HierarchicalChunker | ProceduralChunker |
                               SectionChunker | MixedChunker]
           ──► sentence-transformers ──► ChromaDB (persistent)
           ──► manifest.json (dedup tracking)
```

---

## 2. Chunking Strategy

The central insight is that these five documents have fundamentally different structures, and a one-size-fits-all chunker loses critical context in all of them.

### 2.1 Document-to-Chunker Mapping

| Document | Chunker | Size / Overlap | Rationale |
|---|---|---|---|
| PAPPG (329 pp) | `HierarchicalChunker` | 1200 / 200 | Deep nested sections; section title prepended to every sub-chunk for self-contained retrieval |
| CEF SOP (7 pp) | `ProceduralChunker` | 800 / 150 | Numbered steps must never be split mid-step; step boundaries are preserved |
| SFM SOP (6 pp) | `ProceduralChunker` | 800 / 150 | Same as CEF — short, dense, step-oriented |
| Damage Assessment (128 pp) | `SectionChunker` | 1000 / 200 | Clear section structure; moderate size; page numbers tracked |
| Applicant Handbook (134 pp) | `MixedChunker` | 1000 / 150 | Narrative/guide style; paragraph-aware splitting with section context |

### 2.2 Chunker Design Decisions

**HierarchicalChunker (PAPPG)**  
The PAPPG is a 329-page policy guide with deeply nested sections like "C.2.a.ii". The most important design choice here is **prepending the section header to every sub-chunk**: `[Section: C.2 Eligible Applicants]\n\n<chunk text>`. Without this, a chunk that says "the applicant must submit Form X" is uninterpretable without its section context. This adds ~40 chars of overhead per chunk but dramatically improves retrieval precision.

**ProceduralChunker (CEF & SFM SOPs)**  
These are 6–7 page dense SOPs where procedural steps are numbered. Splitting mid-step creates chunks like "3. The PM shall verify" with no resolution, destroying the meaning. The chunker identifies step start patterns (e.g., `\d+\.\s`, `Step \d`) and treats each complete step as an atomic unit, only splitting when a single step exceeds the size limit.

**SectionChunker (Damage Assessment)**  
A straightforward section-boundary-aware chunker. The DA Manual has a clear chapter/section structure that maps well to section detection heuristics. Chunk sizes are slightly larger (1000 chars) to keep procedure descriptions intact.

**MixedChunker (Applicant Handbook)**  
The Handbook uses a mix of narrative prose and structured lists. The chunker splits first on double newlines (paragraph boundaries), merges small paragraphs until the chunk budget is hit, then falls back to character-level splitting. This preserves readability without splitting a paragraph in half.

### 2.3 Overlap Strategy

All chunkers use overlap (150–200 chars) to handle **boundary questions** — queries that require content spanning two adjacent chunks. Without overlap, a question whose answer sits exactly on a chunk boundary would retrieve neither chunk with high confidence.

---

## 3. Embedding Model

**Model:** `all-MiniLM-L6-v2` (sentence-transformers, local, ~90MB)

**Why this model:**  
- No API cost or latency — fully local inference
- 384-dimensional embeddings — compact and fast to query in ChromaDB
- Strong asymmetric retrieval: trained for sentence similarity tasks, handles long passages vs. short queries well
- FEMA documents are procedural English text — no specialized domain embedding is needed

**Trade-off acknowledged:** A domain-tuned model (e.g., fine-tuned on legal/regulatory text) would improve recall on jargon-heavy queries. With more time, I'd evaluate `legal-bert-base-uncased` or `msmarco-distilbert-base-v4` on a FEMA-specific evaluation set.

---

## 4. Vector Store

**Store:** ChromaDB (persistent local)

**Why ChromaDB:**  
- Zero-infrastructure: runs as an embedded library, persists to disk, no server needed
- Cosine similarity configured at collection level (`hnsw:space: cosine`)
- Metadata filtering built in (could filter by document type without re-embedding)
- Fast enough for ~1,500 chunks — latency is ~20ms per query

**Trade-off:** Pinecone or Weaviate would add managed scalability, hybrid BM25+vector search, and better metadata filtering. For a local assessment with 5 documents, the complexity isn't justified.

---

## 5. Deduplication (No Duplicate Ingestion)

A `data/ingestion_manifest.json` file tracks each ingested file by:
- **Filename** — primary key
- **MD5 hash** — detects if the same filename was replaced with a different file

On every ingestion run, the pipeline checks `is_already_ingested(filepath)` before processing. If the hash matches, the file is skipped entirely. If the hash differs (file was modified), it's re-ingested and the manifest updated.

ChromaDB `upsert` (instead of `add`) is used as a safety net, so even if the manifest is deleted and the pipeline re-run, it won't create duplicate chunks — it will overwrite by deterministic chunk ID (`{filename}__chunk_{index:05d}`).

---

## 6. Generation

**Model:** Azure OpenAI (GPT-3.5-Turbo via provided endpoint)  
**Temperature:** 0.1 — low to minimize hallucination in factual Q&A  
**Prompt design:** Retrieved chunks are numbered and formatted with their source document, section, page, and similarity score. The system prompt explicitly instructs the model to cite using `(Source: <file>, Section: <section>, Page: <page>)` format and to say so when context is insufficient.

**Conversation history:** The last 6 turns are included in the messages array to support multi-turn follow-up questions without exceeding the context window.

---

## 7. Chat UI (React)

**Stack:** React 18 + Vite + plain CSS (no UI library dependency)

**Key UI decisions:**
- **Metadata panel per message:** Every AI response has a "Show retrieval (N chunks)" button that expands inline — this is per-response, not a global sidebar, so users can compare metadata across turns
- **Score bar visualization:** Each chunk card shows a colored progress bar (green ≥ 0.75, amber ≥ 0.50, red < 0.50) so retrieval quality is immediately scannable without reading numbers
- **Chunk text collapsed by default:** Long chunk texts are collapsed to avoid overwhelming the interface; click to expand
- **Top-K selector:** Exposed in the header (3/5/7/10) so evaluators can see the effect of different retrieval depths
- **Global metadata toggle:** "Show Metadata" button in header auto-opens metadata on all new responses — useful during evaluation

---

## 8. Known Limitations & Improvements

| Limitation | Impact | Fix with more time |
|---|---|---|
| No OCR support | Scanned PDFs return empty pages | Add pytesseract OCR fallback |
| Section detection is heuristic | May misclassify some headers | Use a fine-tuned classifier or TOC parsing |
| No hybrid search (BM25 + vector) | Exact-match queries (acronym lookups like "PAPPG") may rank lower | Add BM25 re-ranking (e.g., BM25Retriever from LangChain) |
| Conversation history is in-memory | Restarts lose history | Store in Redis or SQLite |
| No document cross-reference resolution | "see Section 5.1.2" in PAPPG loses context | Build a cross-reference index during ingestion |
| Acronym expansion | "CEF" in a query doesn't automatically expand to "Cost Estimating Format" | Add acronym dictionary pre-processing step |
| Chunk quality not evaluated | Hard to know if chunking is optimal | Build an eval set of 50 question/answer pairs, measure MRR and Recall@K |
