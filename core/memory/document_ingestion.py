from __future__ import annotations

"""Document Knowledge ingestion (blueprint section 38).

    Document -> Parser -> Chunk/Structure Extraction
        -> Entity + Relation Extraction -> Document Knowledge Graph
        -> semantic/vector index -> Retrieval -> Reasoning

The blueprint's own non-negotiable rule for this pipeline: "A
document-derived statement is evidence, not automatically: USER
believes X." Every fact this module stores is tagged namespace
"DOCUMENT" (see SemanticMemory.classify_namespace, Phase 2) and keeps
its source document id, so nothing downstream can accidentally
present "the manual says X" as "you told me X".

Honest scope, stated plainly:

    * Chunking is deterministic (paragraph/sentence splitting with a
      max size) -- reliable, no NLU needed.
    * Every chunk is stored as retrievable evidence (namespace
      DOCUMENT, predicate "excerpt") regardless of whether structured
      facts could be pulled from it -- this alone makes a whole
      document's content searchable through the existing FAISS index,
      which is real, working document Q&A capability on its own.
    * A small set of GENERIC declarative-sentence patterns ("X is Y",
      "X contains Y", "X uses Y", "X requires Y") additionally extract
      structured (subject, predicate, value) facts where the sentence
      is clean enough to match. This is intentionally LOW-RECALL,
      HIGH-PRECISION -- it will miss plenty of real facts phrased
      differently. It is not a claim to general document NLU; that is
      exactly the class of problem the blueprint reserves for SLM/LLM
      escalation, not native pattern matching.
"""

import re
import time
import uuid
from typing import Any, Dict, List, Optional

_MAX_CHUNK_CHARS = 800

_GENERIC_FACT_PATTERNS = [
    (re.compile(r"^\s*(.+?)\s+(?:is|are)\s+(.+?)\.?\s*$", re.I), "is"),
    (re.compile(r"^\s*(.+?)\s+contains?\s+(.+?)\.?\s*$", re.I), "contains"),
    (re.compile(r"^\s*(.+?)\s+uses?\s+(.+?)\.?\s*$", re.I), "uses"),
    (re.compile(r"^\s*(.+?)\s+requires?\s+(.+?)\.?\s*$", re.I), "requires"),
]
_MAX_SUBJECT_WORDS = 6  # a match this long on either side is probably not a clean SVO fact


def chunk_document(text: str, max_chunk_chars: int = _MAX_CHUNK_CHARS) -> List[str]:
    """Deterministic paragraph-first chunking with a hard size cap.
    No NLU -- this is the reliable "Parser / Chunk Extraction" step."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]
    chunks: List[str] = []
    for para in paragraphs:
        if len(para) <= max_chunk_chars:
            chunks.append(para)
            continue
        sentences = re.split(r"(?<=[.!?])\s+", para)
        current = ""
        for sentence in sentences:
            if current and len(current) + len(sentence) + 1 > max_chunk_chars:
                chunks.append(current.strip())
                current = sentence
            else:
                current = f"{current} {sentence}".strip()
        if current.strip():
            chunks.append(current.strip())
    return chunks


def _extract_generic_facts(chunk: str) -> List[Dict[str, str]]:
    """Low-recall, high-precision generic SVO extraction. See module
    docstring for the honest scope statement."""
    facts = []
    for sentence in re.split(r"(?<=[.!?])\s+", chunk):
        sentence = sentence.strip()
        if not sentence or len(sentence) > 200:
            continue
        for pattern, predicate in _GENERIC_FACT_PATTERNS:
            match = pattern.match(sentence)
            if not match:
                continue
            subject = match.group(1).strip(" .,")
            value = match.group(2).strip(" .,")
            if not subject or not value:
                continue
            if len(subject.split()) > _MAX_SUBJECT_WORDS or len(value.split()) > _MAX_SUBJECT_WORDS * 2:
                continue  # too long to be a clean fact -- likely mis-matched a complex sentence
            facts.append({"subject": subject.lower(), "predicate": predicate, "value": value})
            break  # one predicate per sentence keeps this conservative
    return facts


def ingest_document(memory_manager: Any, text: str, doc_id: str, source_label: Optional[str] = None) -> Dict[str, Any]:
    """Run the full pipeline: chunk -> store retrievable evidence ->
    attempt generic fact extraction -> persist, everything tagged
    namespace=DOCUMENT with doc_id kept as provenance.

    Returns a summary dict (never raises for a single bad chunk --
    ingestion of a large document should not abort partway through
    because one paragraph didn't match a pattern).
    """
    semantic = getattr(memory_manager, "semantic", memory_manager)
    if semantic is None or not hasattr(semantic, "remember"):
        return {"doc_id": doc_id, "chunks_stored": 0, "facts_extracted": 0, "error": "no semantic memory available"}

    source = source_label or f"document:{doc_id}"
    chunks = chunk_document(text)
    chunks_stored = 0
    facts_extracted = 0

    for index, chunk in enumerate(chunks):
        try:
            semantic.remember(
                subject=f"document:{doc_id}",
                predicate="excerpt",
                value=chunk,
                confidence=1.0,  # confidence the TEXT was ingested verbatim, not that its claims are true
                importance=0.4,
                source=source,
                tags=["document", doc_id, f"chunk_{index}"],
                namespace="DOCUMENT",
            )
            chunks_stored += 1
        except Exception:
            continue

        for fact in _extract_generic_facts(chunk):
            try:
                semantic.remember(
                    subject=fact["subject"],
                    predicate=fact["predicate"],
                    value=fact["value"],
                    confidence=0.5,  # generic pattern match, not a confirmed personal statement
                    importance=0.3,
                    source=source,
                    tags=["document", doc_id, "extracted_fact"],
                    namespace="DOCUMENT",
                )
                facts_extracted += 1
            except Exception:
                continue

    return {
        "doc_id": doc_id,
        "chunks_stored": chunks_stored,
        "facts_extracted": facts_extracted,
        "ingested_at": time.time(),
    }
