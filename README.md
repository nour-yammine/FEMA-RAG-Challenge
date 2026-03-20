# FEMA RAG Chat Application

A Retrieval-Augmented Generation (RAG) pipeline and React chat interface for querying FEMA Public Assistance documents.

For a **submission-style design write-up** (chunking rationale, env vars, retrieval scoring, API/UI contract), see **[DESIGN.md](./DESIGN.md)**.

To generate **`DESIGN.pdf`** from that file (requires `fpdf2` and `markdown` — e.g. `pip install fpdf2 markdown` in the backend venv):

```bash
python scripts/export_design_pdf.py
```

DejaVu fonts are downloaded on first run into `scripts/.fonts/` (ignored by git).

---

## Architecture Overview

```
fema-rag/
├── backend/          # FastAPI + ChromaDB + Azure OpenAI
│   ├── ingestion/    # PDF parsing + document-specific chunking
│   ├── retrieval/    # ChromaDB vector retrieval
│   ├── generation/   # LLM answer generation with Azure OpenAI
│   └── main.py       # FastAPI app (REST API)
├── frontend/         # React + Vite chat UI
│   └── src/
│       └── components/
└── pdfs/             # Place your 5 FEMA PDFs here
```

### Chunking Strategy Per Document

| Document | Chunker | Chunk Size | Strategy |
|---|---|---|---|
| PAPPG (329 pages) | `HierarchicalChunker` | 1200 chars / 200 overlap | Header-aware recursive split; section title prepended to each chunk |
| CEF SOP (7 pages) | `ProceduralChunker` | 800 chars / 150 overlap | Step-preserving; keeps numbered steps intact |
| SFM SOP (6 pages) | `ProceduralChunker` | 800 chars / 150 overlap | Same as CEF |
| Damage Assessment (128 pages) | `SectionChunker` | 1000 chars / 200 overlap | Section-boundary-aware splitting |
| PA Applicant Handbook (134 pages) | `MixedChunker` | 1000 chars / 150 overlap | Paragraph-aware with section context |

### Deduplication

A `data/ingestion_manifest.json` file tracks each PDF by its MD5 hash. If you run ingestion again on an already-ingested file (unchanged), it is silently skipped.  
To force re-ingestion of a specific file, delete its entry from the manifest (or pass `--force` to the ingest script).

### Document-aware improvements (re-ingest to apply)

After upgrading chunking/retrieval logic, run **`python -m ingestion.ingest --pdf-dir ../pdfs --force`** once so Chroma picks up:

- **Hierarchy:** `section_path` breadcrumbs (e.g. `Chapter 2 > 2.1 Overview`) stored in metadata and chunk text prefixes.
- **Tables:** `pdfplumber` table extraction appended as **markdown** blocks per page when grid lines are detected.
- **Acronyms:** Query-time expansion (see `FEMA_ACRONYM_EXPANSIONS` in `config.py`) improves embedding match for PA, CEF, PAPPG, etc.
- **Cross-references:** Up to `CROSS_REF_MAX_EXTRA_QUERIES` (default 2) extra vector searches from phrases like “see Section …” / form refs mined from the question and top chunks.

Set `CROSS_REF_MAX_EXTRA_QUERIES=0` in `.env` to disable follow-up retrieval.

---

## Prerequisites

- Python 3.10+
- Node.js 18+
- Your 5 FEMA PDF files (place them in `pdfs/`)
- Azure OpenAI credentials (fill in `.env`)

---

## Step-by-Step Setup

### Step 1 — Place the PDF Files

Copy your 5 FEMA PDFs into the `pdfs/` folder:

```
pdfs/
├── Public_Assistance_Program_and_Policy_Guide.pdf
├── Cost_Estimating_Format_SOP.pdf
├── Strategic_Funds_Management_SOP.pdf
├── Damage_Assessment_Operations_Manual.pdf
└── PA_Applicant_Handbook.pdf
```

> The exact filenames don't matter — the system detects document type by keywords in the filename.

---

### Step 2 — Configure Environment Variables

```bash
cd backend
# Windows PowerShell:
# Copy-Item .env.example .env
#
# macOS/Linux:
cp .env.example .env
```

Open `backend/.env` and fill in your Azure OpenAI credentials:

```
AZURE_OPENAI_API_KEY=your_key_here
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=your_deployment_name
AZURE_OPENAI_API_VERSION=2024-02-01
```

#### Security note (for GitHub push / zip)
Do not commit `backend/.env`. It contains your API key(s).

If you use Git, verify before the first commit:
```bash
git status
```
Confirm `backend/.env` is not shown as something to commit.

---

### Step 3 — Install Backend Dependencies

```bash
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

---

### Step 4 — Ingest the PDF Documents

```bash
# Still in backend/ with venv activated
python -m ingestion.ingest --pdf-dir ../pdfs

# To force re-ingest a specific file (ignores manifest):
python -m ingestion.ingest --pdf-dir ../pdfs --force Cost_Estimating_Format_SOP.pdf
```

Expected output:
```
[manifest] Cost_Estimating_Format_SOP.pdf → NEW — ingesting...
[chunker]  ProceduralChunker applied → 47 chunks
[chroma]   Stored 47 chunks ✓

[manifest] Public_Assistance_Program_and_Policy_Guide.pdf → NEW — ingesting...
[chunker]  HierarchicalChunker applied → 724 chunks
[chroma]   Stored 724 chunks ✓
...
Ingestion complete. Total chunks in vector store: 1,203
```

On the second run (no changes):
```
[manifest] Cost_Estimating_Format_SOP.pdf → ALREADY INGESTED (hash match) — skipping
...
Nothing new to ingest.
```

---

### Step 5 — Start the Backend API

```bash
# In backend/ with venv activated
uvicorn main:app --reload --port 8000
```

API will be available at `http://localhost:8000`  
Swagger docs: `http://localhost:8000/docs`

---

### Step 6 — Install & Start the Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend available at `http://localhost:5173`

---

## Run All 15 Test Questions
After you've ingested PDFs and started the backend, you can automatically run every test question and export a combined report (JSON + Markdown).

```bash
# From repo root
python backend/run_test_questions.py --base-url http://localhost:8000 --top-k 5
```

The script writes outputs to `outputs/` (created automatically).

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/chat` | Send a message, get answer + retrieval metadata |
| `GET` | `/ingestion-status` | See what documents are ingested |
| `GET` | `/health` | Health check |
| `DELETE` | `/conversation/{id}` | Clear a conversation's history |

### Chat Request/Response

```json
POST /chat
{
  "message": "What is the Cost Estimating Format?",
  "conversation_id": "abc123",   // optional, omit to start new conversation
  "top_k": 5                     // optional, default 5
}
```

```json
{
  "answer": "The Cost Estimating Format (CEF) is a FEMA tool used for...",
  "conversation_id": "abc123",
  "sources": [
    {
      "chunk_id": "cef-sop-chunk-0042",
      "text": "The CEF is used for large projects exceeding...",
      "score": 0.912,
      "source_document": "Cost_Estimating_Format_SOP.pdf",
      "page_number": 2,
      "section": "2. Purpose",
      "chunk_strategy": "ProceduralChunker",
      "chunk_index": 42
    }
  ],
  "num_chunks_retrieved": 5,
  "model_used": "gpt-35-turbo"
}
```

---



