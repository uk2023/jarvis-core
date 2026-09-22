from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple, Union

# Mobile/PRoot safety: prevent native numerical libraries from creating a
# large implicit worker pool. Explicit ONNX session options below provide the
# actual per-session bound.
for _name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_name, "1")

import faiss
import networkx as nx
import numpy as np
from ..runtime.memory_limits import apply_process_limits, low_memory_session_options, memory_guard
apply_process_limits()

import onnxruntime as ort
from tokenizers import Tokenizer

try:
    from ..runtime.log import log_event
except ImportError:  # pragma: no cover - defensive, keeps this module standalone-importable
    def log_event(tag: str, message: str, level: str = "info") -> None:
        pass


class FastONNXEmbedder:
    """Lightweight CPU-only embedder using ONNX Runtime for ARM64 / Termux."""

    def __init__(self, model_path: str = "all-MiniLM-L6-v2.onnx", tokenizer_path: str = "tokenizer.json"):
        self.model_path = model_path
        self.tokenizer_path = tokenizer_path
        self.vector_dim = 384
        if not os.path.exists(model_path) or not os.path.exists(tokenizer_path):
            log_event("onnx_embedder", f"{model_path} or {tokenizer_path} not found!", level="warning")
        # THE CRASH (fixed 2026-09-14). Thread count was capped here,
        # but the CPU memory arena was still ON and optimisation was set
        # to ORT_ENABLE_ALL, which builds a second, fully-optimised copy
        # of the graph in memory at load time. Combined with
        # onnx_embedder.py's completely unconstrained session (see that
        # file), these two sessions were the ~1.7GB spike in UK's
        # resource samples that got the process killed with 789MB free.
        session_options = low_memory_session_options(ort)
        self.session = ort.InferenceSession(
            model_path,
            sess_options=session_options,
            providers=["CPUExecutionProvider"],
        )
        self.tokenizer = Tokenizer.from_file(tokenizer_path)
        self.tokenizer.enable_padding(length=128, pad_id=0, pad_token="[PAD]")
        self.tokenizer.enable_truncation(max_length=128)

    def get_sentence_embedding_dimension(self) -> int:
        return self.vector_dim

    def encode(self, sentences: Union[str, List[str]], show_progress_bar: bool = False) -> np.ndarray:
        is_single = isinstance(sentences, str)
        text_list = [sentences] if is_single else sentences
        encoded_batch = [self.tokenizer.encode(t) for t in text_list]
        input_ids = np.array([e.ids for e in encoded_batch], dtype=np.int64)
        attention_mask = np.array([e.attention_mask for e in encoded_batch], dtype=np.int64)
        token_type_ids = np.array([e.type_ids for e in encoded_batch], dtype=np.int64)
        inputs = {"input_ids": input_ids, "attention_mask": attention_mask, "token_type_ids": token_type_ids}
        outputs = self.session.run(None, inputs)
        embeddings = outputs[0]
        mask_expanded = np.expand_dims(attention_mask, -1)
        sum_embeddings = np.sum(embeddings * mask_expanded, axis=1)
        sum_mask = np.clip(mask_expanded.sum(axis=1), a_min=1e-9, a_max=None)
        pooled = sum_embeddings / sum_mask
        norms = np.linalg.norm(pooled, axis=1, keepdims=True)
        normalized = (pooled / np.clip(norms, a_min=1e-9, a_max=None)).astype(np.float32)
        return normalized[0] if is_single else normalized


# Provenance refinement (UK's "H2O" / "verify before trusting" ask,
# 2026-09-11 discussion): confidence alone doesn't distinguish "came
# from a citable/observed source" from "LLM guessed this." source_type
# is a small, closed classification layered ON TOP of the existing
# `source` free-text field -- it doesn't replace it.
#   verified       -- externally checkable (web search result, a
#                      directly-observed correction, JARVIS's own
#                      hardcoded identity/runtime facts) or explicitly
#                      confirmed by UK (e.g. via /confirm_rule).
#   user_stated    -- UK said it directly in conversation (a fact
#                      about himself, or an explicit behavioral rule).
#                      Trusted, but distinct from "verified" since nothing
#                      independently checked it.
#   llm_unverified -- produced by JARVIS's own reasoning/LLM inference
#                      with no external check (e.g. a self-authored rule
#                      proposal, an idle-consolidation guess). Should be
#                      hedged in responses until upgraded.
#   unknown        -- default/legacy. Every row written before this
#                      field existed hydrates as "unknown" rather than
#                      a guessed classification, so old data is never
#                      silently overstated as trustworthy.
SOURCE_TYPES = ("verified", "user_stated", "llm_unverified", "unknown")
_SOURCE_TYPE_RANK = {"unknown": 0, "llm_unverified": 1, "user_stated": 2, "verified": 3}

# Explicit, exact-match classification of `source` strings already in
# use across the codebase (see remember() call sites in brain.py,
# user_rules.py, identity/, translator.py, memory_consolidator.py).
# Deliberately NOT a fuzzy/substring guess -- an unrecognized source
# string defaults to "unknown" (see _infer_source_type) rather than
# being misclassified as trustworthy by accident.
_SOURCE_TYPE_MAP = {
    "user_stated_rule": "user_stated",
    "user_request": "user_stated",
    "identity_bootstrap": "verified",
    "identity_self_record": "verified",
    "runtime_checkpoint": "verified",
    "personalized_typo_learning": "verified",
    "self_reasoning": "llm_unverified",
    "idle_consolidation": "llm_unverified",
}


def _infer_source_type(source: Optional[str]) -> str:
    """Best-effort classification for callers that don't explicitly
    pass source_type (keeps every existing remember() call site
    working unchanged). Unrecognized/blank sources default to
    "unknown", never to something more trusted than that."""
    if not source:
        return "unknown"
    return _SOURCE_TYPE_MAP.get(str(source).strip(), "unknown")


@dataclass
class Knowledge:
    """A single piece of semantic knowledge in JARVIS's long-term memory."""
    knowledge_id: str
    subject: str
    predicate: str
    value: Any
    confidence: float = 0.5
    importance: float = 0.5
    source: Optional[str] = None
    created_at: float = 0.0
    updated_at: float = 0.0
    evidence_count: int = 1
    tags: List[str] = None
    # See SOURCE_TYPES / _infer_source_type above.
    source_type: str = "unknown"
    # Namespace separation (blueprint section 63): PERSONAL/PROJECT/
    # DOCUMENT/WORLD/SYSTEM/EXPERIENCE, so a document-derived statement
    # is never conflated with "user believes X", and a rule the user
    # stated about JARVIS's own behavior isn't conflated with a
    # personal preference fact.
    namespace: str = "PERSONAL"
    # Contradiction handling (blueprint section 40): when a new value
    # for the same subject+predicate arrives, the PRIOR value is kept
    # here instead of being silently discarded. Resolution strategy is
    # explicitly "most recent wins for 'current truth'" -- the older
    # value remains inspectable, it is not re-derived from anything
    # fancier (no directness/repeated-evidence weighting yet).
    history: List[Dict[str, Any]] = None

    def __post_init__(self):
        if self.tags is None:
            self.tags = []
        if self.history is None:
            self.history = []
        now = time.time()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = self.created_at

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Knowledge":
        tags = data.get("tags", [])
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except json.JSONDecodeError:
                tags = []
        history = data.get("history", [])
        if isinstance(history, str):
            try:
                history = json.loads(history)
            except json.JSONDecodeError:
                history = []
        value = data.get("value")
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                pass
        source = data.get("source")
        # Legacy rows migrated by the ALTER TABLE ... DEFAULT 'unknown'
        # (see _init_sqlite_db) all read back as the literal string
        # "unknown", not NULL -- so re-run inference on that stored
        # value too, not just on a missing one, otherwise a real,
        # derivable classification (e.g. source="user_stated_rule" ->
        # user_stated) would stay stuck at "unknown" forever after
        # migration. A row explicitly saved with a real source_type
        # (anything other than "unknown") is left exactly as stored.
        stored_source_type = data.get("source_type")
        source_type = stored_source_type if stored_source_type and stored_source_type != "unknown" else _infer_source_type(source)
        return cls(
            knowledge_id=data["knowledge_id"], subject=data["subject"], predicate=data["predicate"], value=value,
            confidence=float(data.get("confidence", 0.5)), importance=float(data.get("importance", 0.5)),
            source=source, created_at=float(data.get("created_at", time.time())),
            updated_at=float(data.get("updated_at", time.time())), evidence_count=int(data.get("evidence_count", 1)), tags=tags,
            namespace=data.get("namespace") or "PERSONAL", history=history, source_type=source_type,
        )


class SemanticMemory:
    """Long-term knowledge store of JARVIS (Android PRoot Optimized)."""
    VERSION = "0.3.6"

    def __init__(self, db_path: str = "database/jarvis.db", faiss_index_path: str = "database/jarvis_faiss.index",
                 max_knowledge: int = 10000, model_path: str = "all-MiniLM-L6-v2.onnx", tokenizer_path: str = "tokenizer.json"):
        self.db_path = db_path
        self.faiss_index_path = faiss_index_path
        self.max_knowledge = max(1, int(max_knowledge))
        self._lock = threading.RLock()
        self._db_connection: Optional[sqlite3.Connection] = None
        self._init_sqlite_db()
        log_event("semantic_memory", "Loading ONNX Fast Embedder & FAISS Vector Store...", level="info")
        self.embedder = FastONNXEmbedder(model_path=model_path, tokenizer_path=tokenizer_path)
        self.vector_dim = self.embedder.get_sentence_embedding_dimension()
        self.faiss_index = faiss.IndexIDMap2(faiss.IndexFlatL2(self.vector_dim))
        self.id_to_faiss_idx: Dict[str, int] = {}
        self.faiss_idx_to_id: Dict[int, str] = {}
        self._next_faiss_id = 1
        self.graph = nx.DiGraph()
        self._hydrate_stores()
        self.created_at = time.time()
        self.updated_at = self.created_at

    def _get_db_connection(self) -> sqlite3.Connection:
        """One persistent connection, reused for the lifetime of this
        SemanticMemory instance -- serialized by self._lock, safe under
        check_same_thread=False.

        BUG THIS FIXES: every one of the ~14 call sites below used to do
        `with self._lock, self._get_db_connection() as conn: ...`, and
        each call to _get_db_connection() opened a BRAND NEW sqlite3
        connection to the same WAL-mode database file. `with conn:` only
        wraps a transaction (commit/rollback) -- it does NOT close the
        connection (that's how Python's sqlite3 module works: Connection
        is its own context manager for transactions only). So every
        search/find/get/statistics call left one more connection open,
        forever, for the rest of the process's life. Verified: after
        1000 calls in this exact pattern, open file descriptors on the
        process went from 7 to 88 with no bound in sight -- on a 20-day
        Termux session with continuous background learning, that is a
        real, unbounded resource leak, and a very plausible contributor
        to the database ballooning to hundreds of MB while `/memory_inspect`
        showed almost nothing in it.
        """
        if self._db_connection is None:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._db_connection = conn
        return self._db_connection

    def close(self) -> None:
        """Flush WAL back into the main database file and release the
        connection. Previously nothing ever called an equivalent of this
        for semantic memory, and the sibling SQLiteStore.close() existed
        but was never wired into shutdown either -- so a session ending
        via Ctrl+C (SIGINT) never got a final checkpoint at all, on top
        of the leaked per-call connections above."""
        with self._lock:
            if self._db_connection is not None:
                try:
                    self._db_connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                except sqlite3.Error:
                    pass
                self._db_connection.close()
                self._db_connection = None

    def _init_sqlite_db(self) -> None:
        with self._lock, self._get_db_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS knowledge (
                    knowledge_id TEXT PRIMARY KEY, subject TEXT NOT NULL, predicate TEXT NOT NULL, value TEXT NOT NULL,
                    confidence REAL NOT NULL, importance REAL NOT NULL, source TEXT, created_at REAL NOT NULL,
                    updated_at REAL NOT NULL, evidence_count INTEGER NOT NULL, tags TEXT NOT NULL, faiss_id INTEGER
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_subject ON knowledge(subject);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_predicate ON knowledge(predicate);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sub_pred ON knowledge(subject, predicate);")
            try:
                conn.execute("SELECT faiss_id FROM knowledge LIMIT 1;")
            except sqlite3.OperationalError:
                conn.execute("ALTER TABLE knowledge ADD COLUMN faiss_id INTEGER;")
            try:
                conn.execute("SELECT namespace FROM knowledge LIMIT 1;")
            except sqlite3.OperationalError:
                conn.execute("ALTER TABLE knowledge ADD COLUMN namespace TEXT NOT NULL DEFAULT 'PERSONAL';")
            try:
                conn.execute("SELECT history FROM knowledge LIMIT 1;")
            except sqlite3.OperationalError:
                conn.execute("ALTER TABLE knowledge ADD COLUMN history TEXT NOT NULL DEFAULT '[]';")
            try:
                conn.execute("SELECT source_type FROM knowledge LIMIT 1;")
            except sqlite3.OperationalError:
                # Existing rows get the SQL-level default 'unknown' on
                # this ALTER. _hydrate_stores/from_dict additionally
                # re-infers from `source` for anything that maps to a
                # better classification (see _infer_source_type) --
                # this column default is just the safe floor.
                conn.execute("ALTER TABLE knowledge ADD COLUMN source_type TEXT NOT NULL DEFAULT 'unknown';")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_faiss_id ON knowledge(faiss_id) WHERE faiss_id IS NOT NULL;")
            conn.commit()

    def _hydrate_stores(self) -> None:
        with self._lock, self._get_db_connection() as conn:
            rows = [dict(row) for row in conn.execute("SELECT * FROM knowledge").fetchall()]
            if not rows:
                return
            max_existing = max((int(r["faiss_id"]) for r in rows if r.get("faiss_id") is not None), default=0)
            next_id = max_existing + 1
            rows_needing_id = [r for r in rows if r.get("faiss_id") is None]
            for row in rows_needing_id:
                row["faiss_id"] = next_id
                next_id += 1
                conn.execute("UPDATE knowledge SET faiss_id = ? WHERE knowledge_id = ?", (row["faiss_id"], row["knowledge_id"]))
            if rows_needing_id:
                conn.commit()
            self._next_faiss_id = next_id
            texts_to_embed, faiss_ids = [], []
            for row in rows:
                item = Knowledge.from_dict(row)
                self._add_to_graph(item)
                faiss_id = int(row["faiss_id"])
                self.id_to_faiss_idx[item.knowledge_id] = faiss_id
                self.faiss_idx_to_id[faiss_id] = item.knowledge_id
                texts_to_embed.append(f"{item.subject} {item.predicate} {str(item.value)}")
                faiss_ids.append(faiss_id)
            loaded_ok = False
            if os.path.exists(self.faiss_index_path):
                try:
                    candidate = faiss.read_index(self.faiss_index_path)
                    if candidate.ntotal == len(faiss_ids):
                        self.faiss_index = candidate
                        loaded_ok = True
                except Exception:
                    loaded_ok = False
            if not loaded_ok and texts_to_embed:
                self._rebuild_faiss_batch(texts_to_embed, faiss_ids)

    def _rebuild_faiss_batch(self, texts: List[str], ids: List[int]) -> None:
        vectors = self.embedder.encode(texts, show_progress_bar=False).astype(np.float32)
        if vectors.ndim != 2 or vectors.shape[0] != len(ids) or vectors.shape[1] != self.vector_dim:
            vectors = np.asarray(vectors, dtype=np.float32).reshape(len(ids), self.vector_dim)
        self.faiss_index = faiss.IndexIDMap2(faiss.IndexFlatL2(self.vector_dim))
        self.faiss_index.add_with_ids(vectors, np.asarray(ids, dtype=np.int64))
        self._save_faiss_to_disk()

    def _faiss_single_vector(self, vector: np.ndarray) -> np.ndarray:
        """Normalize one embedding to FAISS's required (1, dimension) shape."""
        array = np.asarray(vector, dtype=np.float32)
        if array.size != self.vector_dim:
            raise ValueError(f"Embedding dimension mismatch: expected {self.vector_dim} values, got shape {array.shape}.")
        return array.reshape(1, self.vector_dim)

    # Namespace separation (blueprint section 63). A native, deterministic
    # classifier -- no LLM cost. Explicit caller-supplied namespace (see
    # remember()'s new parameter) always wins; this is only the default
    # when the caller doesn't know/care.
    _NAMESPACE_SYSTEM_SUBJECTS = {"jarvis_rule"}
    _NAMESPACE_PROJECT_SUBJECTS = {"jarvis", "project", "organism"}
    # Predicates where a NEW value should ADD to what's already known,
    # not silently replace it -- a real, observed bug: "meri hobby
    # coding hai" then later "but my hobby is singing also" resulted in
    # hobby=coding being discarded entirely and replaced with
    # hobby="singing also", then a THIRD statement flipped it back to
    # just "coding" again -- treating a person's hobbies (which a
    # person can genuinely have several of at once) as if only one
    # could ever be true, the same way "name" or "girlfriend's name"
    # correctly only ever has one true value. This is a closed,
    # deliberately curated set of predicates known to plausibly have
    # multiple simultaneous true values -- not opened up to every
    # predicate, since most facts (name, birthday, city) genuinely are
    # single-valued and SHOULD replace on correction.
    _MULTI_VALUE_PREDICATE_PREFIXES = ("hobby", "hobbies", "likes", "dislikes", "favourite_")

    @classmethod
    def _is_multi_value_predicate(cls, predicate: str) -> bool:
        pred = (predicate or "").strip().lower()
        return any(pred == p or pred.startswith(p) for p in cls._MULTI_VALUE_PREDICATE_PREFIXES)

    @classmethod
    def classify_namespace(cls, subject: str, source: Optional[str] = None) -> str:
        subject_l = (subject or "").strip().lower()
        source_l = (source or "").strip().lower()
        if subject_l in cls._NAMESPACE_SYSTEM_SUBJECTS or "rule" in source_l:
            return "SYSTEM"
        if "document" in source_l or "file" in source_l or "pdf" in source_l:
            return "DOCUMENT"
        if subject_l == "user":
            return "PERSONAL"
        if subject_l in cls._NAMESPACE_PROJECT_SUBJECTS:
            return "PROJECT"
        if source_l in ("experience", "chat"):
            return "EXPERIENCE"
        return "WORLD"

    def remember(self, subject: str, predicate: str, value: Any, confidence: float = 0.5, importance: float = 0.5,
                 source: Optional[str] = None, tags: Optional[List[str]] = None, namespace: Optional[str] = None,
                 source_type: Optional[str] = None) -> Knowledge:
        subject, predicate = self._normalize(subject), self._canonical_predicate(predicate)
        if not subject or not predicate:
            raise ValueError("subject and predicate cannot be empty.")
        resolved_namespace = namespace or self.classify_namespace(subject, source)
        # Caller-supplied source_type always wins over inference (lets
        # e.g. confirm_self_rule() explicitly assert "user_stated" even
        # though the underlying `source` string alone would only infer
        # "llm_unverified"). Falls back to inferring from `source` when
        # the caller doesn't know/care, same pattern as namespace above.
        resolved_source_type = source_type if source_type in SOURCE_TYPES else _infer_source_type(source)
        with self._lock:
            existing = self._find_by_trace(subject, predicate)
            if existing is not None:
                old_val_norm = self._normalize(existing.value)
                new_val_norm = self._normalize(value)
                value_changed = old_val_norm != new_val_norm

                # MULTI-VALUE ACCUMULATION (see _MULTI_VALUE_PREDICATE_
                # PREFIXES above): for predicates like hobby/likes/
                # favourite_*, a genuinely new, different value is an
                # ADDITION to what's already true, not a correction
                # replacing it. Combine into a single "A, B" value
                # BEFORE the normal contradiction-handling path below,
                # so the existing graph/FAISS update logic (which
                # already correctly handles value_changed=True) applies
                # to the COMBINED value rather than needing a separate,
                # untested code path.
                if value_changed and self._is_multi_value_predicate(predicate):
                    existing_parts = [p.strip() for p in str(existing.value).split(",") if p.strip()]
                    new_part = str(value).strip()
                    already_present = any(self._normalize(p) == self._normalize(new_part) for p in existing_parts)
                    # SEMANTIC duplicate check (Bug #10): "ghoomna" and
                    # "travel karna" are literally different strings
                    # (the exact-match check above misses them) but
                    # mean the same thing -- without this, restating a
                    # hobby/like in different words kept accumulating
                    # near-duplicate entries forever. Reuses the SAME
                    # embedder already used for retrieval, no new
                    # dependency or model.
                    if not already_present and self.embedder is not None and existing_parts:
                        try:
                            new_vec = self.embedder.encode(new_part)
                            for part in existing_parts:
                                part_vec = self.embedder.encode(part)
                                denom = (np.linalg.norm(new_vec) * np.linalg.norm(part_vec))
                                similarity = float(np.dot(new_vec, part_vec) / denom) if denom > 0 else 0.0
                                if similarity >= 0.80:
                                    already_present = True
                                    break
                        except Exception:
                            pass
                    if not already_present:
                        value = ", ".join(existing_parts + [new_part])
                        new_val_norm = self._normalize(value)
                    else:
                        # Re-stating a hobby/like already on file --
                        # nothing actually changed, just reinforces
                        # evidence via the normal path below.
                        value = existing.value
                        value_changed = False

                # M6 (2026-09-11 roadmap Phase 7): confidence/provenance-
                # weighted contradiction resolution, replacing PURE
                # recency-wins for the specific case that actually
                # matters -- a LESS-trusted source overwriting a MORE-
                # trusted one. Checked before the normal contradiction
                # path below: if this new value has a LOWER source_type
                # rank than what's already on file (e.g. an unverified
                # LLM guess arriving after a web-verified or UK-confirmed
                # fact) AND the existing fact has some real evidence
                # behind it already, do NOT silently overwrite -- record
                # the new value as a contested candidate instead and
                # keep the trusted value current. A same-or-higher-trust
                # contradiction (the common case: UK correcting his own
                # stated fact) still resolves immediately, unchanged
                # from before.
                if value_changed:
                    existing_rank = _SOURCE_TYPE_RANK.get(existing.source_type, 0)
                    new_rank = _SOURCE_TYPE_RANK.get(resolved_source_type, 0)
                    if new_rank < existing_rank and existing.evidence_count >= 2:
                        existing.history.append({
                            "contested_candidate": True,
                            "proposed_value": value,
                            "proposed_source_type": resolved_source_type,
                            "proposed_confidence": confidence,
                            "existing_value_kept": existing.value,
                            "flagged_at": time.time(),
                        })
                        if "contested_pending_review" not in existing.tags:
                            existing.tags = existing.tags + ["contested_pending_review"]
                        existing.evidence_count += 1
                        existing.updated_at = time.time()
                        self._save_knowledge_to_db(existing, faiss_id=self.id_to_faiss_idx.get(existing.knowledge_id))
                        self.updated_at = existing.updated_at
                        self._save_faiss_to_disk()
                        return existing

                # Contradiction handling (blueprint section 40): "never
                # silently overwrite important facts". Previously
                # `existing.value = value` on the next line simply
                # discarded whatever was there before -- USER --lives_in-->
                # X became USER --lives_in--> Y with X unrecoverable.
                # The prior value now survives in history, timestamped,
                # so a contradiction is a recorded event, not data loss.
                # Resolution strategy is explicit and simple: most recent
                # confirmed value wins for "current truth" (recency),
                # which is one of the blueprint's named strategies --
                # directness/repeated-evidence weighting is not attempted.
                if value_changed:
                    existing.history.append({
                        "value": existing.value,
                        "confidence": existing.confidence,
                        "source": existing.source,
                        "replaced_at": time.time(),
                    })
                existing.evidence_count += 1
                existing.confidence = self._merge_confidence(existing.confidence, confidence)
                existing.importance = max(existing.importance, self._clamp(importance))
                existing.updated_at = time.time()
                existing.value = value
                existing.namespace = namespace or existing.namespace or resolved_namespace
                if source:
                    existing.source = source
                # Provenance can only go UP on a re-assertion of the
                # SAME value (corroboration/confirmation should never
                # make a fact look less trustworthy than it already
                # was). A genuinely CHANGED value is a fresh assertion
                # with its own provenance -- the old value's trust
                # level does not carry over to a different claim.
                if value_changed:
                    existing.source_type = resolved_source_type
                else:
                    if _SOURCE_TYPE_RANK.get(resolved_source_type, 0) > _SOURCE_TYPE_RANK.get(existing.source_type, 0):
                        existing.source_type = resolved_source_type
                if tags:
                    existing.tags = list(set(existing.tags + (tags or [])))
                existing_faiss_id = self.id_to_faiss_idx.get(existing.knowledge_id)
                self._save_knowledge_to_db(existing, faiss_id=existing_faiss_id)
                if value_changed:
                    if self.graph.has_edge(existing.subject, old_val_norm):
                        self.graph.remove_edge(existing.subject, old_val_norm)
                    self._add_to_graph(existing)
                    if existing_faiss_id is not None:
                        text_to_embed = f"{existing.subject} {existing.predicate} {str(existing.value)}"
                        vector = self.embedder.encode(text_to_embed).astype(np.float32)
                        self.faiss_index.remove_ids(np.asarray([existing_faiss_id], dtype=np.int64))
                        self.faiss_index.add_with_ids(self._faiss_single_vector(vector), np.asarray([existing_faiss_id], dtype=np.int64))
                self.updated_at = existing.updated_at
                self._save_faiss_to_disk()
                return existing
            now = time.time()
            knowledge = Knowledge(
                knowledge_id=str(uuid.uuid4()), subject=subject, predicate=predicate, value=value,
                confidence=self._clamp(confidence), importance=self._clamp(importance), source=source,
                created_at=now, updated_at=now, evidence_count=1, tags=list(tags or []),
                namespace=resolved_namespace, source_type=resolved_source_type,
            )
            faiss_id = self._next_faiss_id
            self._next_faiss_id += 1
            self._save_knowledge_to_db(knowledge, faiss_id=faiss_id)
            self._add_to_graph(knowledge)
            text_to_embed = f"{knowledge.subject} {knowledge.predicate} {str(knowledge.value)}"
            vector = self.embedder.encode(text_to_embed).astype(np.float32)
            self.faiss_index.add_with_ids(self._faiss_single_vector(vector), np.asarray([faiss_id], dtype=np.int64))
            self.id_to_faiss_idx[knowledge.knowledge_id] = faiss_id
            self.faiss_idx_to_id[faiss_id] = knowledge.knowledge_id
            self.updated_at = now
            self._prune()
            self._save_faiss_to_disk()
            return knowledge

    def forget(self, knowledge_id: str) -> bool:
        with self._lock:
            item = self.get(knowledge_id)
            if not item:
                return False
            with self._get_db_connection() as conn:
                conn.execute("DELETE FROM knowledge WHERE knowledge_id = ?", (knowledge_id,))
                conn.commit()
            val_norm = self._normalize(item.value)
            if self.graph.has_edge(item.subject, val_norm):
                self.graph.remove_edge(item.subject, val_norm)
            if knowledge_id in self.id_to_faiss_idx:
                faiss_id = self.id_to_faiss_idx.pop(knowledge_id)
                self.faiss_idx_to_id.pop(faiss_id, None)
                self.faiss_index.remove_ids(np.asarray([faiss_id], dtype=np.int64))
            self.updated_at = time.time()
            self._save_faiss_to_disk()
            return True

    def list_all(self, limit: int = 500) -> List["Knowledge"]:
        with self._lock, self._get_db_connection() as conn:
            rows = [dict(row) for row in conn.execute("SELECT * FROM knowledge ORDER BY updated_at DESC LIMIT ?", (max(1, int(limit)),)).fetchall()]
        return [Knowledge.from_dict(row) for row in rows]

    # Cosine floor for FAISS hits. 0.70 was far too strict in practice:
    # facts are embedded as "user favourite color black" while real queries
    # arrive as Hinglish ("mera favourite color batao aur favorite hobby?"),
    # and MiniLM scores that pair well below 0.70 -- so genuinely relevant
    # facts were discarded and retrieval returned nothing. 0.45 recovers
    # them while still excluding unrelated rows. Tunable without a code
    # edit via JARVIS_SEMANTIC_SIM_THRESHOLD.
    DEFAULT_SIMILARITY_THRESHOLD = float(os.getenv("JARVIS_SEMANTIC_SIM_THRESHOLD", "0.45"))

    def semantic_search(self, query: str, similarity_threshold: Optional[float] = None, max_candidate_cap: int = 20,
                        top_k: Optional[int] = None) -> List[Knowledge]:
        """Retrieve semantically similar knowledge using the single FAISS index."""
        return [item for item, _score in self.semantic_search_scored(
            query, similarity_threshold=similarity_threshold, max_candidate_cap=max_candidate_cap, top_k=top_k,
        )]

    def semantic_search_scored(self, query: str, similarity_threshold: Optional[float] = None, max_candidate_cap: int = 20,
                                top_k: Optional[int] = None) -> List[Tuple["Knowledge", float]]:
        """Same retrieval as semantic_search, but also returns each
        hit's cosine similarity. UK's #4 recall/learning/memory
        proposal (neuro-symbolic recall) needs the actual score, not
        just a threshold-filtered list, to check HOW MUCH the top
        match leads the second-best one before trusting an embedding-
        based (as opposed to exact regex) recall -- see NativeReasoner.
        _try_embedding_recall's confidence-gap gate."""
        if similarity_threshold is None:
            similarity_threshold = self.DEFAULT_SIMILARITY_THRESHOLD
        if top_k is not None:
            max_candidate_cap = max(1, int(top_k))
        with self._lock:
            if self.faiss_index.ntotal == 0:
                return []
            query_vector = self.embedder.encode(query).astype(np.float32)
            k_search = min(max_candidate_cap, self.faiss_index.ntotal)
            distances, indices = self.faiss_index.search(self._faiss_single_vector(query_vector), k_search)
            active_facts = []
            for dist, idx in zip(distances[0], indices[0]):
                idx = int(idx)
                if idx != -1 and idx in self.faiss_idx_to_id:
                    cosine_sim = float(1.0 - (dist / 2.0))
                    if cosine_sim >= similarity_threshold:
                        item = self.get(self.faiss_idx_to_id[idx])
                        if item:
                            active_facts.append((item, cosine_sim))
            return active_facts

    def hybrid_search(self, query: str, limit: int = 5, similarity_threshold: Optional[float] = None, lexical_fallback_limit: int = 5) -> List[Knowledge]:
        semantic_results = self.semantic_search(query, similarity_threshold=similarity_threshold, top_k=limit)
        if len(semantic_results) >= limit:
            return semantic_results[:limit]
        seen_ids = {item.knowledge_id for item in semantic_results}
        lexical_results: List[Knowledge] = []
        for item in self.search(query, limit=lexical_fallback_limit):
            if item.knowledge_id not in seen_ids:
                lexical_results.append(item)
                seen_ids.add(item.knowledge_id)
            if len(semantic_results) + len(lexical_results) >= limit:
                break
        return (semantic_results + lexical_results)[:limit]

    def get_trimmed_context(self, query: str, subject: Optional[str] = None, similarity_threshold: float = 0.70) -> str:
        facts = self.semantic_search(query, similarity_threshold=similarity_threshold)
        if not facts and not subject:
            return ""
        context_lines = [f"Fact: {f.subject} {f.predicate} {f.value}" for f in facts]
        if subject:
            graph_limit = max(3, len(facts) * 2)
            for r in self.get_graph_relations(subject, max_limit=graph_limit):
                context_lines.append(f"Relation: {r['subject']} -> {r['predicate']} -> {r['target']}")
        return "\n".join(context_lines)

    def get_graph_relations(self, subject: str, max_limit: int = 5) -> List[Dict[str, Any]]:
        subject = self._normalize(subject)
        with self._lock:
            if subject not in self.graph:
                return []
            relations = []
            for neighbor in self.graph.successors(subject):
                edge_data = self.graph.get_edge_data(subject, neighbor)
                relations.append({"subject": subject, "target": neighbor, "predicate": edge_data.get("predicate", "related_to")})
                if len(relations) >= max_limit:
                    break
            return relations

    def find(self, subject: str, predicate: Optional[str] = None, value: Any = None) -> List[Knowledge]:
        subject = self._normalize(subject)
        query = "SELECT * FROM knowledge WHERE subject = ?"
        params: List[Any] = [subject]
        if predicate is not None:
            query += " AND predicate = ?"
            params.append(self._normalize(predicate))
        if value is not None:
            query += " AND value = ?"
            params.append(json.dumps(value) if not isinstance(value, str) else value)
        with self._lock, self._get_db_connection() as conn:
            return [Knowledge.from_dict(dict(row)) for row in conn.execute(query, params).fetchall()]

    def find_by_subject(self, subject: str, limit: Optional[int] = None) -> List[Knowledge]:
        results = self.find(subject=subject)
        return results if limit is None else results[:max(0, int(limit))]

    def find_by_predicate(self, predicate: str, limit: Optional[int] = None) -> List[Knowledge]:
        predicate = self._normalize(predicate)
        with self._lock, self._get_db_connection() as conn:
            rows = conn.execute("SELECT * FROM knowledge WHERE predicate = ? ORDER BY updated_at DESC", (predicate,)).fetchall()
        results = [Knowledge.from_dict(dict(row)) for row in rows]
        return results if limit is None else results[:max(0, int(limit))]

    def find_by_tag(self, tag: str, limit: Optional[int] = None) -> List[Knowledge]:
        target = self._normalize(tag)
        with self._lock, self._get_db_connection() as conn:
            rows = conn.execute("SELECT * FROM knowledge ORDER BY updated_at DESC").fetchall()
        results = []
        for row in rows:
            item = Knowledge.from_dict(dict(row))
            if any(self._normalize(t) == target for t in item.tags):
                results.append(item)
                if limit is not None and len(results) >= max(0, int(limit)):
                    break
        return results

    # Words that carry no retrieval signal in Hinglish/English chat. Without
    # this, "batao"/"kya"/"hai" match half the table and drown real facts.
    _STOPWORDS = {
        "the", "and", "for", "with", "what", "who", "was", "are", "you", "your",
        "tell", "about", "from", "this", "that", "have", "has", "can", "how",
        "mera", "meri", "mere", "mujhe", "muje", "kya", "hai", "hain", "batao",
        "bata", "aur", "koi", "abhi", "wala", "wali", "kaun", "kaunsa", "tha",
    }

    def search(self, query: str, limit: int = 20) -> List[Knowledge]:
        """Lexical fallback retrieval, matched PER TERM.

        Previously this built a single LIKE pattern out of the entire
        user sentence:

            WHERE subject LIKE '%mera favourite color batao aur favorite hobby?%'

        which can only match if a stored row literally contains the whole
        sentence -- so in normal chat it returned 0 rows every single time.
        Combined with the FAISS threshold being set too high for Hinglish,
        that made `relevant_knowledge` and `graph_relations` empty on every
        turn: JARVIS held the fact "user favourite color black" in its own
        database and still answered "abhi tak mere database mein missing
        hai", because retrieval never surfaced it. That is the actual
        reason answers felt ungrounded / purely LLM-generated.

        Now each meaningful term is matched independently and rows are
        ranked by how many distinct query terms they hit, so partial and
        reordered phrasings still retrieve the right fact.
        """
        terms = [
            term for term in re.findall(r"[a-z0-9_]+", self._normalize(query))
            if len(term) > 2 and term not in self._STOPWORDS
        ]
        if not terms:
            return []
        terms = terms[:8]  # bound the SQL size for very long inputs

        clauses = []
        params: List[Any] = []
        for term in terms:
            clauses.append("(subject LIKE ? OR predicate LIKE ? OR value LIKE ? OR tags LIKE ?)")
            params.extend([f"%{term}%"] * 4)

        sql = f"""
            SELECT * FROM knowledge
            WHERE {" OR ".join(clauses)}
            ORDER BY importance DESC, confidence DESC, updated_at DESC
        """
        with self._lock, self._get_db_connection() as conn:
            rows = [dict(row) for row in conn.execute(sql, params).fetchall()]

        def term_hits(row: Dict[str, Any]) -> int:
            haystack = " ".join(
                str(row.get(field) or "") for field in ("subject", "predicate", "value", "tags")
            ).lower()
            return sum(1 for term in terms if term in haystack)

        rows.sort(
            key=lambda row: (
                term_hits(row),
                float(row.get("importance") or 0.0),
                float(row.get("confidence") or 0.0),
                float(row.get("updated_at") or 0.0),
            ),
            reverse=True,
        )
        return [Knowledge.from_dict(row) for row in rows[:limit]]

    def get(self, knowledge_id: str) -> Optional[Knowledge]:
        with self._lock, self._get_db_connection() as conn:
            row = conn.execute("SELECT * FROM knowledge WHERE knowledge_id = ?", (knowledge_id,)).fetchone()
            return Knowledge.from_dict(dict(row)) if row else None

    def update_confidence(self, knowledge_id: str, confidence: float) -> Optional[Knowledge]:
        with self._lock:
            item = self.get(knowledge_id)
            if item is None:
                return None
            item.confidence = self._clamp(confidence)
            item.updated_at = time.time()
            self._save_knowledge_to_db(item, faiss_id=self.id_to_faiss_idx.get(knowledge_id))
            self.updated_at = item.updated_at
            return item

    def set_tags(self, knowledge_id: str, tags: List[str]) -> Optional[Knowledge]:
        """Replace (not merge) a knowledge item's tags outright.
        Unlike remember(), which always UNIONS incoming tags with
        existing ones (deliberately, so an unrelated caller's
        remember() call never accidentally drops a tag it doesn't know
        about), some transitions need a tag actually REMOVED, not just
        added alongside the old one -- e.g. rejecting a self-authored
        rule (see Brain.reject_self_rule()) needs "pending_confirmation"
        gone, replaced by "rejected", not both present at once."""
        with self._lock:
            item = self.get(knowledge_id)
            if item is None:
                return None
            item.tags = list(tags)
            item.updated_at = time.time()
            self._save_knowledge_to_db(item, faiss_id=self.id_to_faiss_idx.get(knowledge_id))
            self.updated_at = item.updated_at
            return item

    def reinforce(self, knowledge_id: str, confidence_delta: float = 0.1) -> Optional[Knowledge]:
        item = self.get(knowledge_id)
        if item is None:
            return None
        return self.update_confidence(knowledge_id, item.confidence + float(confidence_delta))

    def weaken(self, knowledge_id: str, confidence_delta: float = 0.1) -> Optional[Knowledge]:
        item = self.get(knowledge_id)
        if item is None:
            return None
        return self.update_confidence(knowledge_id, item.confidence - float(confidence_delta))

    def decay_unused(self, days_threshold: float = 14.0, confidence_delta: float = 0.02,
                      confidence_floor: float = 0.15, limit: int = 200) -> List[str]:
        """Spaced-repetition's other half (see NativeReasoner.
        _reinforce_recalled_fact): a fact that keeps getting recalled
        should strengthen; a fact nobody has touched in weeks should
        quietly fade, the way real memory does, instead of every
        stored fact sitting at equal permanent weight forever.

        Restricted to namespace=="PERSONAL" only -- identity, system,
        document, and project facts are not personal-recall-dependent
        preferences and must not be allowed to silently weaken just
        because they weren't asked about recently. Facts already at
        or below confidence_floor are left alone (nothing decays to
        zero and disappears; it settles at a low-but-present floor).

        Returns the list of knowledge_ids that were decayed this call.
        """
        cutoff = time.time() - (max(1.0, float(days_threshold)) * 86400.0)
        decayed: List[str] = []
        for item in self.list_all(limit=limit):
            if item.namespace != "PERSONAL":
                continue
            if item.updated_at > cutoff:
                continue
            if item.confidence <= confidence_floor:
                continue
            self.weaken(item.knowledge_id, confidence_delta=confidence_delta)
            decayed.append(item.knowledge_id)
        return decayed

    def list_contested_facts(self, limit: int = 50) -> List["Knowledge"]:
        """Facts with at least one pending contested candidate (see
        remember()'s M6 contradiction-resolution branch) -- a
        less-trusted source tried to overwrite this fact and was
        held back rather than silently applied. UK reviews these via
        resolve_contested_fact()."""
        try:
            items = self.find_by_tag("contested_pending_review", limit=limit)
        except Exception:
            items = []
        return items

    def resolve_contested_fact(self, knowledge_id: str, accept_new_value: bool) -> Optional["Knowledge"]:
        """UK's decision on a contested fact (see list_contested_facts()).
        accept_new_value=True applies the most recent contested
        candidate's value (as a fresh, explicitly-approved assertion,
        source_type="user_stated" since UK just reviewed it);
        accept_new_value=False simply clears the contested tag and
        keeps the existing value, with the rejected candidate staying
        in history for the record either way."""
        with self._lock:
            item = self.get(knowledge_id)
            if item is None:
                return None
            contested_entries = [h for h in (item.history or []) if isinstance(h, dict) and h.get("contested_candidate")]
            item.tags = [t for t in item.tags if t != "contested_pending_review"]
            if accept_new_value and contested_entries:
                latest = contested_entries[-1]
                item.value = latest.get("proposed_value", item.value)
                item.source_type = "user_stated"
                item.confidence = self._clamp(max(item.confidence, float(latest.get("proposed_confidence", item.confidence) or 0.0)))
            item.updated_at = time.time()
            self._save_knowledge_to_db(item, faiss_id=self.id_to_faiss_idx.get(knowledge_id))
            self.updated_at = item.updated_at
            return item

    def snapshot(self, limit: Optional[int] = None) -> Dict[str, Any]:
        with self._lock:
            query = "SELECT * FROM knowledge ORDER BY updated_at ASC"
            params = []
            if limit is not None:
                query += " LIMIT ?"
                params.append(max(0, int(limit)))
            with self._get_db_connection() as conn:
                rows = conn.execute(query, params).fetchall()
            return {"version": self.VERSION, "count": self.count, "max_knowledge": self.max_knowledge,
                    "created_at": self.created_at, "updated_at": self.updated_at,
                    "knowledge": [Knowledge.from_dict(dict(row)).to_dict() for row in rows]}

    def restore(self, snapshot: Dict[str, Any]) -> None:
        if not isinstance(snapshot, dict):
            return
        raw_knowledge = snapshot.get("knowledge", [])
        if not isinstance(raw_knowledge, list):
            return
        for data in raw_knowledge:
            if not isinstance(data, dict):
                continue
            try:
                knowledge = Knowledge.from_dict(data)
                if self.get(knowledge.knowledge_id) is None:
                    self.remember(subject=knowledge.subject, predicate=knowledge.predicate, value=knowledge.value,
                                  confidence=knowledge.confidence, importance=knowledge.importance, source=knowledge.source,
                                  tags=knowledge.tags, source_type=knowledge.source_type)
            except Exception as exc:
                log_event("semantic_memory", f"restore warning: {exc}", level="warning")
        self.updated_at = time.time()
        self._save_faiss_to_disk()

    @property
    def count(self) -> int:
        with self._lock, self._get_db_connection() as conn:
            return conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]

    def clear(self) -> None:
        with self._lock:
            with self._get_db_connection() as conn:
                conn.execute("DELETE FROM knowledge")
                conn.commit()
            self.graph.clear()
            self.faiss_index = faiss.IndexIDMap2(faiss.IndexFlatL2(self.vector_dim))
            self.id_to_faiss_idx.clear()
            self.faiss_idx_to_id.clear()
            self._next_faiss_id = 1
            if os.path.exists(self.faiss_index_path):
                try:
                    os.remove(self.faiss_index_path)
                except OSError:
                    pass
            self.updated_at = time.time()

    def _prune(self) -> None:
        current_count = self.count
        if current_count <= self.max_knowledge:
            return
        excess = current_count - self.max_knowledge
        with self._lock, self._get_db_connection() as conn:
            rows = conn.execute("""
                SELECT knowledge_id FROM knowledge
                ORDER BY importance ASC, confidence ASC, updated_at ASC
                LIMIT ?
            """, (excess,)).fetchall()
            to_remove = [row["knowledge_id"] for row in rows]
        for k_id in to_remove:
            self.forget(k_id)

    def _save_knowledge_to_db(self, knowledge: Knowledge, faiss_id: Optional[int] = None) -> None:
        val_str = json.dumps(knowledge.value) if not isinstance(knowledge.value, str) else knowledge.value
        tags_str = json.dumps(knowledge.tags)
        history_str = json.dumps(knowledge.history)
        with self._get_db_connection() as conn:
            conn.execute("""
                INSERT INTO knowledge (
                    knowledge_id, subject, predicate, value, confidence, importance, source,
                    created_at, updated_at, evidence_count, tags, faiss_id, namespace, history, source_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(knowledge_id) DO UPDATE SET
                    value=excluded.value, confidence=excluded.confidence, importance=excluded.importance,
                    source=excluded.source, updated_at=excluded.updated_at, evidence_count=excluded.evidence_count,
                    tags=excluded.tags, faiss_id=excluded.faiss_id, namespace=excluded.namespace, history=excluded.history,
                    source_type=excluded.source_type;
            """, (knowledge.knowledge_id, knowledge.subject, knowledge.predicate, val_str, knowledge.confidence,
                  knowledge.importance, knowledge.source, knowledge.created_at, knowledge.updated_at,
                  knowledge.evidence_count, tags_str, faiss_id, knowledge.namespace, history_str, knowledge.source_type))
            conn.commit()

    def _add_to_graph(self, item: Knowledge) -> None:
        self.graph.add_node(item.subject, type="subject")
        if isinstance(item.value, str):
            val_str = self._normalize(item.value)
            self.graph.add_node(val_str, type="value")
            self.graph.add_edge(item.subject, val_str, predicate=item.predicate)

    def _save_faiss_to_disk(self) -> None:
        try:
            faiss.write_index(self.faiss_index, self.faiss_index_path)
        except Exception as e:
            log_event("semantic_memory", f"error saving FAISS index to disk: {e}", level="error")

    def _find_by_trace(self, subject: str, predicate: str) -> Optional[Knowledge]:
        items = self.find(subject, predicate)
        return items[0] if items else None

    def _find_exact(self, subject: str, predicate: str, value: Any) -> Optional[Knowledge]:
        items = self.find(subject, predicate)
        for item in items:
            if item.value == value:
                return item
        return None

    @staticmethod
    def _normalize(value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip().lower()

    # Predicates are written from whatever word the user typed, so a single
    # concept was fragmenting across misspellings -- a real database ended up
    # holding "favourite", "favoutite" AND "faviurite" as three unrelated
    # predicates. Nothing could then unify them, so asking "mera favourite
    # color batao" could not reach a fact stored under "favoutite".
    # Canonicalizing at write time keeps one concept as one predicate.
    _PREDICATE_ALIASES = {
        "favourite": "favourite",
        "favorite": "favourite",
        "fav": "favourite",
        "favoutite": "favourite",
        "faviurite": "favourite",
        "favourit": "favourite",
        "favorit": "favourite",
        "pasandida": "favourite",
        "naam": "name",
        "name": "name",
        "hobby": "hobby",
        "hobbies": "hobby",
        "shauk": "hobby",
    }

    @classmethod
    def _canonical_predicate(cls, predicate: Any) -> str:
        """Map a raw, possibly-misspelled predicate onto its canonical form.

        Exact alias first, then a conservative character-overlap check so
        unseen typos of a known predicate ("favourtie") still collapse
        correctly, while genuinely different predicates are left alone.
        """
        normalized = cls._normalize(predicate)
        if not normalized:
            return ""
        normalized = re.sub(r"[^a-z0-9_ ]+", "", normalized).strip()
        normalized = re.sub(r"\s+", "_", normalized)
        if normalized in cls._PREDICATE_ALIASES:
            return cls._PREDICATE_ALIASES[normalized]

        head = normalized.split("_", 1)[0]
        if head in cls._PREDICATE_ALIASES:
            canonical = cls._PREDICATE_ALIASES[head]
            remainder = normalized.split("_", 1)[1] if "_" in normalized else ""
            return f"{canonical}_{remainder}" if remainder else canonical

        for candidate in set(cls._PREDICATE_ALIASES.values()):
            if abs(len(head) - len(candidate)) <= 2 and len(head) >= 4:
                shared = len(set(head) & set(candidate))
                if shared >= max(4, len(candidate) - 2) and head[0] == candidate[0]:
                    return candidate
        return normalized

    @staticmethod
    def _clamp(value: float) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _merge_confidence(old: float, new: float) -> float:
        old = max(0.0, min(1.0, old))
        new = max(0.0, min(1.0, new))
        return old + ((new - old) * 0.25)
