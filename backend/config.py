"""
config.py — Centralized configuration loaded from .env
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Paths ──────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
CHROMA_DB_PATH = os.getenv("CHROMA_DB_PATH", str(DATA_DIR / "chroma_db"))
MANIFEST_PATH = DATA_DIR / "ingestion_manifest.json"

# ── Azure OpenAI ───────────────────────────────────────────────────────────
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-35-turbo")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01")

# ── Embeddings ─────────────────────────────────────────────────────────────
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

# ── Retrieval ──────────────────────────────────────────────────────────────
CHROMA_COLLECTION = "fema_docs"
DEFAULT_TOP_K = int(os.getenv("DEFAULT_TOP_K", "5"))
MAX_CONTEXT_TOKENS = int(os.getenv("MAX_CONTEXT_TOKENS", "4000"))
# Extra vector queries mined from "see Section ..." / form refs (0 disables)
CROSS_REF_MAX_EXTRA_QUERIES = int(os.getenv("CROSS_REF_MAX_EXTRA_QUERIES", "2"))

# Acronym → expansion phrase appended at query time for embedding (order: longer keys first handled by insertion order—put ambiguous short ones carefully)
FEMA_ACRONYM_EXPANSIONS: dict[str, str] = {
    "PAPPG": "Public Assistance Program and Policy Guide",
    "CEF": "Cost Estimating Format",
    "SFM": "Strategic Funds Management",
    "SOP": "Standard Operating Procedure",
    "PA": "FEMA Public Assistance program",
    "PW": "Project Worksheet",
    "PWs": "Project Worksheets",
    "RPA": "Request for Public Assistance",
    "DAAM": "Damage Assessment and Operations Manual",
    "IAP": "Incident Action Plan",
    "PA-C": "Public Assistance-Construction",
    "OMB": "Office of Management and Budget",
}

# ── Document type → chunking strategy mapping ──────────────────────────────
# Matched against lowercase filename — first match wins
DOCUMENT_TYPE_MAP = [
    ("pappg",                "PAPPG",             "HierarchicalChunker"),
    ("public_assistance_program", "PAPPG",         "HierarchicalChunker"),
    ("policy_guide",         "PAPPG",              "HierarchicalChunker"),
    ("cost_estimating",      "CEF_SOP",            "ProceduralChunker"),
    ("cef",                  "CEF_SOP",            "ProceduralChunker"),
    ("strategic_funds",      "SFM_SOP",            "ProceduralChunker"),
    ("startegic",            "SFM_SOP",            "ProceduralChunker"),  # typo in filename
    ("sfm",                  "SFM_SOP",            "ProceduralChunker"),
    ("9570",                 "SFM_SOP",            "ProceduralChunker"),  # matches by form number
    ("damage_assessment",    "DamageAssessment",   "SectionChunker"),
    ("femadaom",             "DamageAssessment",   "SectionChunker"),     # your actual filename
    ("daom",                 "DamageAssessment",   "SectionChunker"),
    ("applicant_handbook",   "ApplicantHandbook",  "MixedChunker"),
    ("app_handbk",           "ApplicantHandbook",  "MixedChunker"),       # abbreviated
    ("handbk",               "ApplicantHandbook",  "MixedChunker"),
    ("fema323",              "ApplicantHandbook",  "MixedChunker"),       # matches by form number
    ("handbook",             "ApplicantHandbook",  "MixedChunker"),
]
def detect_document_type(filename: str) -> tuple[str, str]:
    """
    Returns (document_label, chunker_class_name) for a given PDF filename.
    Falls back to ('Unknown', 'MixedChunker') if no keyword matches.
    """
    lower = filename.lower().replace("-", "_").replace(" ", "_")
    for keyword, label, chunker in DOCUMENT_TYPE_MAP:
        if keyword.replace("-", "_") in lower:
            return label, chunker
    return "Unknown", "MixedChunker"
