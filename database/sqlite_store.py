from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


class SQLiteStore:
    """
    Persistent storage layer for JARVIS.

    SQLite is the durable memory layer.

    Responsibilities:
        - Create database/schema.
        - Store episodic memories.
        - Store semantic knowledge.
        - Retrieve memories.
        - Update confidence/importance.
        - Provide database statistics.

    This class contains NO cognition or learning logic.
    """

    VERSION = "0.1.0"

    def __init__(
        self,
        database_path: str = "database/jarvis.db",
    ):
        self.database_path = Path(database_path)

        self.database_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._lock = threading.RLock()

        self._connection = sqlite3.connect(
            str(self.database_path),
            check_same_thread=False,
        )

        self._connection.row_factory = sqlite3.Row

        self._configure()

        self._initialize_schema()

    # =============================================================
    # DATABASE CONFIGURATION
    # =============================================================

    def _configure(self) -> None:

        with self._connection:

            self._connection.execute(
                "PRAGMA journal_mode=WAL"
            )

            self._connection.execute(
                "PRAGMA foreign_keys=ON"
            )

            self._connection.execute(
                "PRAGMA synchronous=NORMAL"
            )

    # =============================================================
    # SCHEMA
    # =============================================================

    def _initialize_schema(self) -> None:

        with self._lock:

            cursor = self._connection.cursor()

            # -----------------------------------------------------
            # Episodic memory
            # -----------------------------------------------------

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS episodes (
                    episode_id TEXT PRIMARY KEY,

                    timestamp REAL NOT NULL,

                    event_type TEXT NOT NULL,

                    context_json TEXT,
                    action_json TEXT,
                    outcome_json TEXT,

                    importance REAL NOT NULL DEFAULT 0.5,
                    confidence REAL NOT NULL DEFAULT 1.0,

                    source TEXT,

                    tags_json TEXT,

                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_episodes_timestamp
                ON episodes(timestamp)
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_episodes_event_type
                ON episodes(event_type)
                """
            )

            # -----------------------------------------------------
            # Semantic knowledge
            # -----------------------------------------------------

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge (
                    knowledge_id TEXT PRIMARY KEY,

                    subject TEXT NOT NULL,
                    predicate TEXT NOT NULL,

                    value_json TEXT,

                    confidence REAL NOT NULL DEFAULT 0.5,
                    importance REAL NOT NULL DEFAULT 0.5,

                    source TEXT,

                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,

                    evidence_count INTEGER NOT NULL DEFAULT 1,

                    tags_json TEXT
                )
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_knowledge_subject
                ON knowledge(subject)
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_knowledge_predicate
                ON knowledge(predicate)
                """
            )

            # -----------------------------------------------------
            # Organism metadata
            # -----------------------------------------------------

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS organism_meta (
                    key TEXT PRIMARY KEY,
                    value_json TEXT,
                    updated_at REAL NOT NULL
                )
                """
            )

            self._connection.commit()

    # =============================================================
    # EPISODIC MEMORY
    # =============================================================

    def save_episode(
        self,
        episode: Dict[str, Any],
    ) -> None:

        now = time.time()

        with self._lock:

            self._connection.execute(
                """
                INSERT OR REPLACE INTO episodes (
                    episode_id,
                    timestamp,
                    event_type,
                    context_json,
                    action_json,
                    outcome_json,
                    importance,
                    confidence,
                    source,
                    tags_json,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    episode["episode_id"],
                    episode["timestamp"],
                    episode["event_type"],
                    self._json(episode.get("context")),
                    self._json(episode.get("action")),
                    self._json(episode.get("outcome")),
                    episode.get("importance", 0.5),
                    episode.get("confidence", 1.0),
                    episode.get("source"),
                    self._json(episode.get("tags", [])),
                    episode.get("timestamp", now),
                    now,
                ),
            )

            self._connection.commit()

    # =============================================================
    # LOAD EPISODES
    # =============================================================

    def load_episodes(
        self,
        limit: int = 5000,
    ) -> List[Dict[str, Any]]:

        with self._lock:

            rows = self._connection.execute(
                """
                SELECT *
                FROM episodes
                ORDER BY timestamp ASC
                LIMIT ?
                """,
                (max(0, int(limit)),),
            ).fetchall()

        return [
            self._episode_from_row(row)
            for row in rows
        ]

    # =============================================================
    # SEMANTIC KNOWLEDGE
    # =============================================================

    def save_knowledge(
        self,
        knowledge: Dict[str, Any],
    ) -> None:

        now = time.time()

        with self._lock:

            self._connection.execute(
                """
                INSERT OR REPLACE INTO knowledge (
                    knowledge_id,
                    subject,
                    predicate,
                    value_json,
                    confidence,
                    importance,
                    source,
                    created_at,
                    updated_at,
                    evidence_count,
                    tags_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    knowledge["knowledge_id"],
                    knowledge["subject"],
                    knowledge["predicate"],
                    self._json(knowledge.get("value")),
                    knowledge.get("confidence", 0.5),
                    knowledge.get("importance", 0.5),
                    knowledge.get("source"),
                    knowledge.get("created_at", now),
                    knowledge.get("updated_at", now),
                    knowledge.get("evidence_count", 1),
                    self._json(
                        knowledge.get("tags", [])
                    ),
                ),
            )

            self._connection.commit()

    # =============================================================
    # LOAD KNOWLEDGE
    # =============================================================

    def load_knowledge(
        self,
        limit: int = 10000,
    ) -> List[Dict[str, Any]]:

        with self._lock:

            rows = self._connection.execute(
                """
                SELECT *
                FROM knowledge
                ORDER BY updated_at ASC
                LIMIT ?
                """,
                (max(0, int(limit)),),
            ).fetchall()

        return [
            self._knowledge_from_row(row)
            for row in rows
        ]

    # =============================================================
    # DELETE EPISODE
    # =============================================================

    def delete_episode(
        self,
        episode_id: str,
    ) -> bool:

        with self._lock:

            cursor = self._connection.execute(
                """
                DELETE FROM episodes
                WHERE episode_id = ?
                """,
                (episode_id,),
            )

            self._connection.commit()

            return cursor.rowcount > 0

    # =============================================================
    # DELETE KNOWLEDGE
    # =============================================================

    def delete_knowledge(
        self,
        knowledge_id: str,
    ) -> bool:

        with self._lock:

            cursor = self._connection.execute(
                """
                DELETE FROM knowledge
                WHERE knowledge_id = ?
                """,
                (knowledge_id,),
            )

            self._connection.commit()

            return cursor.rowcount > 0

    # =============================================================
    # META
    # =============================================================

    def set_meta(
        self,
        key: str,
        value: Any,
    ) -> None:

        with self._lock:

            self._connection.execute(
                """
                INSERT OR REPLACE INTO organism_meta (
                    key,
                    value_json,
                    updated_at
                )
                VALUES (?, ?, ?)
                """,
                (
                    key,
                    self._json(value),
                    time.time(),
                ),
            )

            self._connection.commit()

    # =============================================================

    def get_meta(
        self,
        key: str,
        default: Any = None,
    ) -> Any:

        with self._lock:

            row = self._connection.execute(
                """
                SELECT value_json
                FROM organism_meta
                WHERE key = ?
                """,
                (key,),
            ).fetchone()

        if row is None:
            return default

        return self._from_json(
            row["value_json"],
            default,
        )

    # =============================================================
    # STATISTICS
    # =============================================================

    def statistics(self) -> Dict[str, Any]:

        with self._lock:

            episodes = self._connection.execute(
                "SELECT COUNT(*) FROM episodes"
            ).fetchone()[0]

            knowledge = self._connection.execute(
                "SELECT COUNT(*) FROM knowledge"
            ).fetchone()[0]

        return {
            "database": str(
                self.database_path
            ),
            "episodes": episodes,
            "knowledge": knowledge,
        }

    # =============================================================
    # CLOSE
    # =============================================================

    def close(self) -> None:

        with self._lock:

            if self._connection is not None:

                self._connection.close()

                self._connection = None

    # =============================================================
    # HELPERS
    # =============================================================

    @staticmethod
    def _json(value: Any) -> str:

        return json.dumps(
            value,
            ensure_ascii=False,
            default=str,
        )

    @staticmethod
    def _from_json(
        value: Optional[str],
        default: Any = None,
    ) -> Any:

        if value is None:
            return default

        try:
            return json.loads(value)

        except (
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ):
            return default

    def _episode_from_row(
        self,
        row: sqlite3.Row,
    ) -> Dict[str, Any]:

        return {
            "episode_id": row["episode_id"],
            "timestamp": row["timestamp"],
            "event_type": row["event_type"],
            "context": self._from_json(
                row["context_json"],
                {},
            ),
            "action": self._from_json(
                row["action_json"],
                None,
            ),
            "outcome": self._from_json(
                row["outcome_json"],
                None,
            ),
            "importance": row["importance"],
            "confidence": row["confidence"],
            "source": row["source"],
            "tags": self._from_json(
                row["tags_json"],
                [],
            ),
        }

    def _knowledge_from_row(
        self,
        row: sqlite3.Row,
    ) -> Dict[str, Any]:

        return {
            "knowledge_id": row["knowledge_id"],
            "subject": row["subject"],
            "predicate": row["predicate"],
            "value": self._from_json(
                row["value_json"],
                None,
            ),
            "confidence": row["confidence"],
            "importance": row["importance"],
            "source": row["source"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "evidence_count": row["evidence_count"],
            "tags": self._from_json(
                row["tags_json"],
                [],
            ),
        }