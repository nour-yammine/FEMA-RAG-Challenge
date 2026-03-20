"""
generation/generator.py — Build a prompt from retrieved chunks and
call the Azure OpenAI API to generate a grounded, cited answer.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional

from openai import AzureOpenAI

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import (
    AZURE_OPENAI_API_KEY,
    AZURE_OPENAI_ENDPOINT,
    AZURE_OPENAI_DEPLOYMENT,
    AZURE_OPENAI_API_VERSION,
    MAX_CONTEXT_TOKENS,
)


# ─────────────────────────────────────────────────────────────────────────────
# Prompt templates
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a precise AI assistant specializing in FEMA Public Assistance policy and procedures.

Your answers must be:
- Grounded ONLY in the provided context chunks — do not use outside knowledge
- Cited: always mention the source document and section for each key claim
  Format: (Source: <filename>, Section: <section name>, Page: <page>)
- Concise but complete: answer the question fully without padding
- Honest: if the context doesn't contain enough information, say so clearly

If the question requires synthesizing information from multiple documents, do so explicitly.
Use bullet points when listing steps or items for clarity.
"""

CONTEXT_TEMPLATE = """--- Context Chunk {i} ---
Document : {source_document}
Hierarchy: {section_path}
Section  : {section}
Page     : {page_number}
Score    : {score}

{text}
"""

USER_TEMPLATE = """Based on the following retrieved context from FEMA documents, answer the question below.

{context_block}

---

Question: {question}

Answer (cite sources inline using the format: Source: <filename>, Section: <section>, Page: <page>):"""


def _build_context_block(chunks: List[dict], max_tokens: int = MAX_CONTEXT_TOKENS) -> str:
    """
    Assemble context chunks into a single string, respecting a rough token budget.
    We approximate tokens as chars / 4.
    """
    budget = max_tokens * 4  # chars budget
    parts = []
    used = 0
    for i, chunk in enumerate(chunks, start=1):
        block = CONTEXT_TEMPLATE.format(
            i=i,
            source_document=chunk["source_document"],
            section_path=chunk.get("section_path") or chunk.get("section") or "",
            section=chunk["section"],
            page_number=chunk["page_number"],
            score=chunk["score"],
            text=chunk["text"],
        )
        if used + len(block) > budget:
            # Include a truncated note if we ran out of budget
            parts.append(f"--- [Context truncated at chunk {i} to stay within token limit] ---")
            break
        parts.append(block)
        used += len(block)
    return "\n".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Generator class
# ─────────────────────────────────────────────────────────────────────────────

class Generator:
    def __init__(self):
        self._client: Optional[AzureOpenAI] = None

    def _get_client(self) -> AzureOpenAI:
        if self._client is None:
            if not AZURE_OPENAI_API_KEY or not AZURE_OPENAI_ENDPOINT:
                raise ValueError(
                    "Azure OpenAI credentials not set. "
                    "Fill in AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT in .env"
                )
            self._client = AzureOpenAI(
                api_key=AZURE_OPENAI_API_KEY,
                azure_endpoint=AZURE_OPENAI_ENDPOINT,
                api_version=AZURE_OPENAI_API_VERSION,
            )
        return self._client

    def generate(
        self,
        question: str,
        chunks: List[dict],
        conversation_history: Optional[List[dict]] = None,
    ) -> str:
        """
        Generate an answer grounded in `chunks`.

        `conversation_history` is a list of {"role": "user"|"assistant", "content": str}
        dicts representing prior turns in the conversation.
        """
        client = self._get_client()

        context_block = _build_context_block(chunks)
        user_message = USER_TEMPLATE.format(
            context_block=context_block,
            question=question,
        )

        # Build message list: system + optional history + current user message
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]

        if conversation_history:
            # Include recent history (last 6 turns to stay within context limit)
            messages.extend(conversation_history[-6:])

        messages.append({"role": "user", "content": user_message})

        response = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=messages,
            temperature=0.1,       # Low temperature for factual Q&A
            max_tokens=1200,
        )

        return response.choices[0].message.content.strip()


# Module-level singleton
generator = Generator()
