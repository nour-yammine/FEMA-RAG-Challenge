"""
run_test_questions.py

Automation helper for the FEMA RAG assessment:
- Sends all 15 test questions to the running backend (`POST /chat`)
- Captures the returned answer and retrieval metadata (`sources`)
- Writes JSON + Markdown outputs that you can submit to the recruiter

Usage (from repo root):
  1) Start backend:
       cd backend
       python -m ingestion.ingest --pdf-dir ../pdfs
       uvicorn main:app --reload --port 8000
  2) Run:
       python backend/run_test_questions.py --base-url http://localhost:8000
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import httpx


TEST_QUESTIONS: List[str] = [
    "What is the Cost Estimating Format (CEF) and what types of projects is it used for?",
    "Who determines which local factors to use when developing a CEF cost estimate, and what factors do they consider?",
    "What is Strategic Funds Management (SFM) and what is its purpose?",
    "What types of entities are eligible to apply for FEMA Public Assistance?",
    "What are the two main types of federal disaster declarations, and what assistance is available under each?",
    "In the CEF process, what is the difference between Part A and Part B of the cost estimate, and who is responsible for each?",
    "When does the SFM SOP NOT apply? What exceptions exist?",
    "Explain the process for a subgrantee to receive PA funding, from the initial Request for Public Assistance through final obligation. Reference the relevant SOPs and guides.",
    "What does the PAPPG say about the use of the words 'must' and 'required' versus 'should' in policy guidance? Why does this distinction matter?",
    "What is the Alternative Procedures Pilot Policy, and how does it change the standard PA process for permanent work projects?",
    "What Construction Specifications Institute (CSI) standards are referenced in the CEF process, and how should unit costs be documented? Specifically, which unit types are acceptable and which are not?",
    "If a subgrantee wants to split Project Worksheets (PWs) to create multiple obligations, under what circumstances is this allowed according to the SFM SOP?",
    "Compare and contrast how the PAPPG and the Applicant Handbook describe the roles of State governments in the PA process. Are there any differences in emphasis or detail?",
    "What is the review cycle for SOPs according to the SFM SOP? Does the SOP automatically expire?",
    "A city sustained damage to a public library and a water treatment plant in the same disaster. Walk through how FEMA would process these as separate projects under the PA program, referencing the relevant cost estimation and fund management procedures.",
]


def _md_escape(text: str) -> str:
    # Minimal escaping so Markdown remains readable.
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _format_sources_markdown(sources: List[Dict[str, Any]]) -> str:
    if not sources:
        return "_No sources returned._"

    lines: List[str] = []
    lines.append("| # | score | chunk_id | doc | page | section_path | section | chunk_strategy |")
    lines.append("| ---: | ---: | --- | --- | ---: | --- | --- | --- |")

    for i, s in enumerate(sources, start=1):
        sec_path = str(s.get("section_path") or s.get("section", "")).replace("\n", " ").strip()
        lines.append(
            "| {i} | {score} | {chunk_id} | {doc} | {page} | {sec_path} | {section} | {strategy} |".format(
                i=i,
                score=str(s.get("score", "")),
                chunk_id=s.get("chunk_id", ""),
                doc=s.get("document_label", s.get("source_document", "")),
                page=s.get("page_number", ""),
                sec_path=sec_path[:120] + ("…" if len(sec_path) > 120 else ""),
                section=str(s.get("section", "")).replace("\n", " ").strip(),
                strategy=s.get("chunk_strategy", ""),
            )
        )

    lines.append("")

    # Include full retrieved chunks (assessment requirement).
    for i, s in enumerate(sources, start=1):
        chunk_text = s.get("text", "")
        lines.append(f"<details><summary>Retrieved chunk #{i}</summary>\n\n")
        lines.append("```text")
        lines.append(_md_escape(chunk_text))
        lines.append("```")
        lines.append("\n</details>\n")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run all 15 FEMA RAG test questions.")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Backend base URL")
    parser.add_argument("--top-k", type=int, default=5, help="Number of retrieved chunks to request")
    parser.add_argument(
        "--output-dir",
        default="outputs",
        help="Directory (relative to repo root) where reports are written",
    )
    parser.add_argument(
        "--conversation-mode",
        choices=["fresh-per-question", "single-conversation"],
        default="fresh-per-question",
        help="Use a new conversation_id for each question or keep one for all",
    )
    parser.add_argument("--timeout-seconds", type=float, default=120.0, help="HTTP timeout per question")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    output_dir = (repo_root / args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_json = output_dir / f"fema_rag_test_questions_{timestamp}.json"
    out_md = output_dir / f"fema_rag_test_questions_{timestamp}.md"

    base = args.base_url.rstrip("/")
    url = f"{base}/chat"

    results: List[Dict[str, Any]] = []

    conversation_id: str | None = None
    if args.conversation_mode == "single-conversation":
        conversation_id = None  # let backend generate first, then reuse

    with httpx.Client(timeout=args.timeout_seconds) as client:
        for idx, question in enumerate(TEST_QUESTIONS, start=1):
            print(f"[{idx}/{len(TEST_QUESTIONS)}] Asking: {question}")

            payload: Dict[str, Any] = {"message": question, "top_k": args.top_k}
            if args.conversation_mode == "single-conversation" and conversation_id:
                payload["conversation_id"] = conversation_id

            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

            if args.conversation_mode == "single-conversation":
                conversation_id = data.get("conversation_id", conversation_id)

            results.append(
                {
                    "question_index": idx,
                    "question": question,
                    "answer": data.get("answer", ""),
                    "conversation_id": data.get("conversation_id", ""),
                    "num_chunks_retrieved": data.get("num_chunks_retrieved", 0),
                    "model_used": data.get("model_used", ""),
                    "sources": data.get("sources", []),
                }
            )

    report: Dict[str, Any] = {
        "generated_at": datetime.now().isoformat(),
        "base_url": base,
        "top_k": args.top_k,
        "conversation_mode": args.conversation_mode,
        "results": results,
    }

    out_json.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    md_lines: List[str] = []
    md_lines.append(f"# FEMA RAG — Test Question Outputs ({timestamp})")
    md_lines.append("")
    md_lines.append(f"- Backend: `{base}`")
    md_lines.append(f"- Top-k: `{args.top_k}`")
    md_lines.append(f"- Conversation mode: `{args.conversation_mode}`")
    md_lines.append("")

    for r in results:
        md_lines.append(f"## Question {r['question_index']}")
        md_lines.append("")
        md_lines.append(f"**Question:** {_md_escape(r['question'])}")
        md_lines.append("")
        md_lines.append("**Answer (as generated):**")
        md_lines.append("")
        md_lines.append("```text")
        md_lines.append(_md_escape(r.get("answer", "")))
        md_lines.append("```")
        md_lines.append("")
        md_lines.append("### Retrieval metadata (sources)")
        md_lines.append("")
        md_lines.append(_format_sources_markdown(r.get("sources", [])))
        md_lines.append("")

    out_md.write_text("\n".join(md_lines), encoding="utf-8")

    print(f"\nWrote JSON: {out_json}")
    print(f"Wrote Markdown: {out_md}")


if __name__ == "__main__":
    main()

