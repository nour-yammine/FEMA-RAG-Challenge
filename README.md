# FEMA RAG Chat Application

A Retrieval-Augmented Generation (RAG) pipeline and React chat interface for querying FEMA Public Assistance documents.

For a **submission-style design write-up** (chunking rationale, env vars, retrieval scoring, API/UI contract), see **[DESIGN.md](./DESIGN.md)**.

To generate **`DESIGN.pdf`** from that file (requires `fpdf2` and `markdown` — e.g. `pip install fpdf2 markdown` in the backend venv):

```bash
python scripts/export_design_pdf.py
```

DejaVu fonts are downloaded on first run into `scripts/.fonts/` (ignored by git).

---

## Quick Setup (recommended for running locally)

This repo is intended to run with a local configuration:

- Secrets: `backend/.env` (NOT committed)
- Template for secrets: `backend/.env.example` (committed, safe placeholders)
- Data: `pdfs/*.pdf` and the local Chroma DB in `backend/data/chroma_db/` (not committed)

See `DESIGN.md` for the deeper architectural rationale.

---

## Prerequisites

- Python 3.10+
- Node.js 18+
- Your 5 FEMA PDF files (expected in `pdfs/`)
- Azure OpenAI credentials (copy `backend/.env.example` to `backend/.env`)

---

## Step-by-Step Setup

### Step 2 — Configure Environment Variables

```bash
cd backend
# Windows PowerShell:
Copy-Item .env.example .env
# macOS/Linux:
# cp .env.example .env
```

Open `backend/.env` and fill in your Azure OpenAI credentials:

```
AZURE_OPENAI_API_KEY=your_key_here
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=your_deployment_name
AZURE_OPENAI_API_VERSION=2024-02-01
```

#### Security note

`backend/.env.example` is committed for reference.
`backend/.env` contains secrets and is ignored by git (do not commit it).

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

## Optional: run test questions

After ingestion and backend start:

```bash
# From repo root
python backend/run_test_questions.py --base-url http://localhost:8000 --top-k 5
```

Outputs go to `outputs/` (created automatically).

## Quick sanity checks

- Backend health: `GET http://localhost:8000/health`
- Use the frontend chat UI at `http://localhost:5173`
