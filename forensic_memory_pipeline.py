#!/usr/bin/env python3

"""
JARVIS ORGANISM — PHASE 2 MEMORY FORENSIC

READ-ONLY FORENSIC TOOL

DOES NOT:
- INSERT
- UPDATE
- DELETE
- COMMIT
- FORGET
- REBUILD FAISS
- SAVE FAISS
- MODIFY NetworkX
"""

from pathlib import Path
import inspect
import sqlite3
import traceback
import json
import sys


# ============================================================
# PATHS
# ============================================================

ROOT = Path(__file__).resolve().parent
DB = ROOT / "database" / "jarvis.db"

FAISS_PATHS = [
    ROOT / "database" / "jarvis_faiss.index",
    ROOT / "jarvis_faiss.index",
]


# ============================================================
# HEADER
# ============================================================

print("\n" + "=" * 100)
print(" JARVIS ORGANISM — PHASE 2 MEMORY FORENSIC")
print(" READ-ONLY / NO DATABASE OR FAISS MODIFICATION")
print("=" * 100)

print("\nROOT")
print("  ", ROOT)
print("CWD")
print("  ", Path.cwd())
print("PYTHON")
print("  ", sys.version)


# ============================================================
# SOURCE FILE INSPECTION
# ============================================================

print("\n" + "=" * 100)
print("1. SOURCE FILE INSPECTION")
print("=" * 100)

SOURCE_FILES = [
    "core/memory/semantic_memory.py",
    "core/memory/memory_manager.py",
    "core/orchestration/brain.py",
    "core/learning/knowledge_builder.py",
    "core/learning/learning_coordinator.py",
]

for rel in SOURCE_FILES:
    path = ROOT / rel

    print("\n" + "-" * 100)
    print(rel)
    print("-" * 100)

    if not path.exists():
        print("❌ FILE NOT FOUND")
        continue

    print("✔ exists")
    print("size:", path.stat().st_size, "bytes")

    try:
        lines = path.read_text(errors="replace").splitlines()

        print("lines:", len(lines))

        # Print important structural definitions
        targets = [
            "class SemanticMemory",
            "class MemoryManager",
            "class Brain",
            "def __init__",
            "def hybrid_search",
            "def semantic_search",
            "def search",
            "def restore",
            "def _hydrate_stores",
            "def _rebuild_faiss_batch",
            "def _save_faiss_to_disk",
            "def remember",
            "def forget",
            "def clear",
            "def build_context",
            "def _extract_fact",
            "def remember_knowledge",
            "auto_accept",
        ]

        for i, line in enumerate(lines, 1):
            stripped = line.strip()

            if any(t in stripped for t in targets):
                print(f"{i:5}: {stripped}")

    except Exception as e:
        print("❌ Could not inspect source:", repr(e))


# ============================================================
# SQLITE CONNECTION
# ============================================================

print("\n" + "=" * 100)
print("2. SQLITE FORENSIC")
print("=" * 100)

if not DB.exists():
    print("❌ DB NOT FOUND:", DB)
    sys.exit(1)

print("DB:", DB)
print("size:", DB.stat().st_size, "bytes")

conn = sqlite3.connect(str(DB))
conn.row_factory = sqlite3.Row


# ============================================================
# SCHEMA
# ============================================================

print("\n[SCHEMA]")

try:
    cols = conn.execute(
        "PRAGMA table_info(knowledge)"
    ).fetchall()

    for c in cols:
        print(
            f"  {c['name']:<20} "
            f"type={c['type']:<12} "
            f"notnull={c['notnull']} "
            f"pk={c['pk']}"
        )

except Exception as e:
    print("❌", repr(e))


# ============================================================
# KNOWLEDGE COUNTS
# ============================================================

print("\n[COUNTS]")

count = conn.execute(
    "SELECT COUNT(*) AS n FROM knowledge"
).fetchone()["n"]

nonnull_faiss = conn.execute(
    "SELECT COUNT(*) AS n "
    "FROM knowledge WHERE faiss_id IS NOT NULL"
).fetchone()["n"]

null_faiss = conn.execute(
    "SELECT COUNT(*) AS n "
    "FROM knowledge WHERE faiss_id IS NULL"
).fetchone()["n"]

print("  knowledge rows       :", count)
print("  non-null faiss_id    :", nonnull_faiss)
print("  null faiss_id        :", null_faiss)


# ============================================================
# FAISS IDs FROM SQLITE
# ============================================================

print("\n[SQLITE FAISS IDS]")

sqlite_rows = conn.execute("""
    SELECT
        knowledge_id,
        subject,
        predicate,
        value,
        confidence,
        importance,
        evidence_count,
        source,
        faiss_id,
        tags
    FROM knowledge
    WHERE faiss_id IS NOT NULL
    ORDER BY faiss_id
""").fetchall()

sqlite_faiss_ids = []

for r in sqlite_rows:
    fid = int(r["faiss_id"])
    sqlite_faiss_ids.append(fid)

    print(
        f"  {fid:4} | "
        f"{r['knowledge_id']} | "
        f"{r['subject']} | "
        f"{r['predicate']} | "
        f"{r['value']}"
    )


# ============================================================
# DUPLICATE SEMANTIC KNOWLEDGE
# ============================================================

print("\n" + "=" * 100)
print("3. DUPLICATE / NORMALIZATION FORENSIC")
print("=" * 100)

try:
    duplicates = conn.execute("""
        SELECT
            lower(subject) AS subject,
            lower(predicate) AS predicate,
            lower(value) AS value,
            COUNT(*) AS n
        FROM knowledge
        GROUP BY
            lower(subject),
            lower(predicate),
            lower(value)
        HAVING COUNT(*) > 1
        ORDER BY n DESC
    """).fetchall()

    if not duplicates:
        print("✔ No exact duplicate SPO triples.")
    else:
        for r in duplicates:
            print(
                f"  DUPLICATE x{r['n']}: "
                f"{r['subject']} | "
                f"{r['predicate']} | "
                f"{r['value']}"
            )

except Exception as e:
    print("❌ duplicate analysis failed:", repr(e))


# ============================================================
# GIRLFRIEND / NAME FORENSIC
# ============================================================

print("\n" + "=" * 100)
print("4. GIRLFRIEND / PARTNER / NAME FORENSIC")
print("=" * 100)

terms = [
    "girlfriend",
    "partner",
    "gf",
    "jaan",
    "sweetheart",
    "name",
    "full_name",
]

for term in terms:

    rows = conn.execute("""
        SELECT
            knowledge_id,
            subject,
            predicate,
            value,
            confidence,
            importance,
            evidence_count,
            source,
            faiss_id
        FROM knowledge
        WHERE
            lower(subject) LIKE ?
            OR lower(predicate) LIKE ?
            OR lower(value) LIKE ?
        ORDER BY confidence DESC, importance DESC
    """, (
        f"%{term}%",
        f"%{term}%",
        f"%{term}%",
    )).fetchall()

    print(f"\nTERM: {term}")

    if not rows:
        print("  -- none --")
        continue

    for r in rows:
        print(
            f"  {r['subject']} | "
            f"{r['predicate']} | "
            f"{r['value']} | "
            f"conf={r['confidence']} | "
            f"imp={r['importance']} | "
            f"evidence={r['evidence_count']} | "
            f"source={r['source']} | "
            f"faiss={r['faiss_id']}"
        )


# ============================================================
# FULL NAME FORENSIC
# ============================================================

print("\n" + "=" * 100)
print("5. FULL-NAME FORENSIC")
print("=" * 100)

rows = conn.execute("""
    SELECT
        knowledge_id,
        subject,
        predicate,
        value,
        confidence,
        importance,
        evidence_count,
        source,
        faiss_id
    FROM knowledge
    WHERE
        lower(predicate) = 'full_name'
        OR lower(subject) = 'user'
        OR lower(value) IN ('uk', 'ujjwal', 'ujjwal kumar')
    ORDER BY updated_at DESC
""").fetchall()

for r in rows:
    print(
        f"  {r['subject']} | "
        f"{r['predicate']} | "
        f"{r['value']} | "
        f"conf={r['confidence']} | "
        f"imp={r['importance']} | "
        f"source={r['source']} | "
        f"faiss={r['faiss_id']}"
    )


# ============================================================
# DISK FAISS
# ============================================================

print("\n" + "=" * 100)
print("6. DISK FAISS FORENSIC")
print("=" * 100)

try:
    import faiss

    for fp in FAISS_PATHS:

        print("\nFAISS:", fp)

        if not fp.exists():
            print("  ❌ missing")
            continue

        print("  size:", fp.stat().st_size)

        try:
            idx = faiss.read_index(str(fp))

            print("  type   :", type(idx).__name__)
            print("  ntotal :", idx.ntotal)
            print("  dim    :", idx.d)

            if hasattr(idx, "id_map"):

                ids = faiss.vector_to_array(idx.id_map)

                print("  ids:", [int(x) for x in ids])

                faiss_set = set(int(x) for x in ids)
                sqlite_set = set(sqlite_faiss_ids)

                print("\n  SQLite IDs :", sorted(sqlite_set))
                print("  FAISS IDs  :", sorted(faiss_set))

                print(
                    "  missing in FAISS:",
                    sorted(sqlite_set - faiss_set)
                )

                print(
                    "  orphan in FAISS:",
                    sorted(faiss_set - sqlite_set)
                )

        except Exception as e:
            print("  ❌ read failed:", repr(e))

except Exception as e:
    print("  ❌ FAISS forensic section failed:", repr(e))


# ============================================================
# SEMANTIC MEMORY IMPORT
# ============================================================

print("\n" + "=" * 100)
print("7. SEMANTIC MEMORY OBJECT FORENSIC")
print("=" * 100)

semantic = None

try:

    from core.memory.semantic_memory import SemanticMemory

    print("✔ imported SemanticMemory")

    semantic_path = ROOT / "database" / "jarvis_faiss.index"

    semantic = SemanticMemory(
        db_path=str(DB),
        faiss_index_path=str(semantic_path),
    )

    print("✔ initialized SemanticMemory")

except Exception as e:

    print("❌ SemanticMemory initialization failed")
    print(repr(e))
    traceback.print_exc()


# ============================================================
# OBJECT STATE
# ============================================================

if semantic is not None:

    print("\n[OBJECT STATE]")

    attributes = [
        "db_path",
        "faiss_index_path",
        "vector_dim",
        "_next_faiss_id",
        "knowledge",
        "id_to_faiss_idx",
        "faiss_idx_to_id",
        "graph",
        "faiss_index",
        "embedder",
    ]

    for name in attributes:

        try:

            if not hasattr(semantic, name):
                print(f"  ❌ {name}: MISSING")
                continue

            value = getattr(semantic, name)

            if name == "knowledge":
                try:
                    print(
                        f"  ✔ knowledge: "
                        f"{len(value)} items"
                    )
                except:
                    print("  ✔ knowledge exists")

            elif name == "id_to_faiss_idx":
                print(
                    f"  ✔ id_to_faiss_idx: "
                    f"{len(value)} mappings"
                )

            elif name == "faiss_idx_to_id":
                print(
                    f"  ✔ faiss_idx_to_id: "
                    f"{len(value)} mappings"
                )

            elif name == "graph":
                try:
                    print(
                        f"  ✔ graph: "
                        f"nodes={value.number_of_nodes()} "
                        f"edges={value.number_of_edges()}"
                    )
                except:
                    print("  ✔ graph exists")

            elif name == "faiss_index":
                try:
                    print(
                        f"  ✔ faiss_index: "
                        f"type={type(value).__name__} "
                        f"ntotal={value.ntotal} "
                        f"dim={value.d}"
                    )
                except:
                    print("  ✔ faiss_index exists")

            elif name == "embedder":
                print(
                    f"  ✔ embedder: "
                    f"{type(value).__name__}"
                )

            else:
                print(f"  ✔ {name}: {value}")

        except Exception as e:
            print(f"  ⚠ {name}: {e}")


# ============================================================
# FUNCTION SIGNATURE FORENSIC
# ============================================================

print("\n" + "=" * 100)
print("8. SEMANTIC MEMORY FUNCTION SIGNATURES")
print("=" * 100)

if semantic is not None:

    methods = [
        "hybrid_search",
        "semantic_search",
        "search",
        "find",
        "get",
        "remember",
        "forget",
        "clear",
        "restore",
        "_hydrate_stores",
        "_rebuild_faiss_batch",
        "_save_faiss_to_disk",
        "_find_by_trace",
        "_add_to_graph",
    ]

    for name in methods:

        print(f"\n{name}")

        if not hasattr(semantic, name):
            print("  ❌ MISSING")
            continue

        try:
            method = getattr(semantic, name)

            print(
                "  signature:",
                inspect.signature(method)
            )

            try:
                print(
                    "  source line:",
                    inspect.getsourcelines(method)[1]
                )
            except:
                pass

        except Exception as e:
            print("  ❌", repr(e))


# ============================================================
# EMBEDDER FORENSIC
# ============================================================

print("\n" + "=" * 100)
print("9. EMBEDDING FORENSIC")
print("=" * 100)

if semantic is not None and hasattr(semantic, "embedder"):

    embedder = semantic.embedder

    print("Embedder class:", type(embedder).__name__)

    try:

        print("embedder methods:")

        for name in [
            "encode",
            "encode_batch",
            "embed",
        ]:

            if hasattr(embedder, name):

                fn = getattr(embedder, name)

                try:
                    print(
                        f"  ✔ {name}",
                        inspect.signature(fn)
                    )
                except:
                    print(f"  ✔ {name}")

    except Exception as e:
        print("⚠", repr(e))

    # Test ONLY encoding; does not mutate memory.
    test_query = "meri girlfriend ka nam btao"

    print("\nTEST QUERY:")
    print(" ", test_query)

    try:

        if hasattr(embedder, "encode"):

            vec = embedder.encode([test_query])

            print("encode() result type:", type(vec))

            try:
                print("shape:", vec.shape)
            except:
                pass

            try:
                print(
                    "first vector length:",
                    len(vec[0])
                )
            except:
                pass

    except Exception as e:

        print("❌ encode failed")
        print(repr(e))
        traceback.print_exc()


# ============================================================
# RAW FAISS SEARCH
# ============================================================

print("\n" + "=" * 100)
print("10. RAW FAISS SEARCH")
print("=" * 100)

if semantic is not None:

    try:

        if not hasattr(semantic, "faiss_index"):
            print("❌ no faiss_index")
        elif not hasattr(semantic, "embedder"):
            print("❌ no embedder")
        else:

            query = "meri girlfriend ka nam btao"

            print("Query:", query)

            vec = semantic.embedder.encode([query])

            # Normalize possible numpy/list result
            import numpy as np

            q = np.asarray(vec, dtype="float32")

            if q.ndim == 1:
                q = q.reshape(1, -1)

            print("Query vector shape:", q.shape)

            index = semantic.faiss_index

            print("Index ntotal:", index.ntotal)
            print("Index dimension:", index.d)

            if q.shape[1] != index.d:
                print(
                    "❌ DIMENSION MISMATCH:",
                    q.shape[1],
                    "!=",
                    index.d
                )

            else:

                distances, ids = index.search(
                    q,
                    min(10, index.ntotal)
                )

                print("\nRAW SEARCH RESULTS")

                for rank, (dist, fid) in enumerate(
                    zip(distances[0], ids[0]),
                    1
                ):

                    print(
                        f"  rank={rank:<3} "
                        f"faiss_id={int(fid):<5} "
                        f"distance={float(dist):.8f}"
                    )

                    # Map ID back to SQLite
                    if int(fid) >= 0:

                        row = conn.execute("""
                            SELECT
                                knowledge_id,
                                subject,
                                predicate,
                                value,
                                confidence,
                                importance,
                                source
                            FROM knowledge
                            WHERE faiss_id = ?
                        """, (int(fid),)).fetchone()

                        if row:

                            print(
                                "       → SQLite:",
                                row["subject"],
                                "|",
                                row["predicate"],
                                "|",
                                row["value"],
                                "| conf=",
                                row["confidence"],
                                "| source=",
                                row["source"],
                            )

                        else:

                            print(
                                "       → ❌ NO SQLITE ROW"
                            )

    except Exception as e:

        print("❌ RAW FAISS SEARCH FAILED")
        print(repr(e))
        traceback.print_exc()


# ============================================================
# SEMANTIC SEARCH — ACTUAL SIGNATURE
# ============================================================

print("\n" + "=" * 100)
print("11. SEMANTIC_SEARCH ACTUAL EXECUTION")
print("=" * 100)

if semantic is not None and hasattr(semantic, "semantic_search"):

    query = "meri girlfriend ka nam btao"

    print("Query:", query)

    try:

        sig = inspect.signature(
            semantic.semantic_search
        )

        print("Signature:", sig)

        params = list(sig.parameters.values())

        print("Parameters:")

        for p in params:
            print(
                " ",
                p.name,
                "=",
                p.default
            )

        # Safe invocation based on common signatures.
        try:

            result = semantic.semantic_search(
                query
            )

        except TypeError:

            result = semantic.semantic_search(
                query=query
            )

        print("\nRESULT TYPE:", type(result).__name__)

        try:
            print(
                json.dumps(
                    result,
                    indent=2,
                    default=str
                )
            )
        except:
            print(result)

    except Exception as e:

        print("❌ semantic_search failed")
        print(repr(e))
        traceback.print_exc()


# ============================================================
# HYBRID SEARCH — ACTUAL SIGNATURE
# ============================================================

print("\n" + "=" * 100)
print("12. HYBRID_SEARCH ACTUAL EXECUTION")
print("=" * 100)

if semantic is not None and hasattr(semantic, "hybrid_search"):

    query = "meri girlfriend ka nam btao"

    print("Query:", query)

    try:

        sig = inspect.signature(
            semantic.hybrid_search
        )

        print("Signature:", sig)

        print("Parameters:")

        for p in sig.parameters.values():
            print(
                " ",
                p.name,
                "=",
                p.default
            )

        try:

            result = semantic.hybrid_search(
                query
            )

        except TypeError:

            result = semantic.hybrid_search(
                query=query
            )

        print("\nRESULT TYPE:", type(result).__name__)

        try:
            print(
                json.dumps(
                    result,
                    indent=2,
                    default=str
                )
            )
        except:
            print(result)

    except Exception as e:

        print("❌ hybrid_search failed")
        print(repr(e))
        traceback.print_exc()


# ============================================================
# GRAPH FORENSIC
# ============================================================

print("\n" + "=" * 100)
print("13. NETWORKX GRAPH FORENSIC")
print("=" * 100)

if semantic is not None and hasattr(semantic, "graph"):

    graph = semantic.graph

    try:

        print(
            "nodes:",
            graph.number_of_nodes()
        )

        print(
            "edges:",
            graph.number_of_edges()
        )

        print("\nEdges:")

        for edge in list(graph.edges(data=True))[:100]:

            print(" ", edge)

        print("\nRelevant graph nodes:")

        for node in graph.nodes:

            text = str(node).lower()

            if any(
                x in text
                for x in [
                    "girlfriend",
                    "partner",
                    "akanksha",
                    "user",
                    "jaan",
                ]
            ):

                print(
                    " ",
                    node
                )

    except Exception as e:

        print("❌ graph inspection failed:", repr(e))


# ============================================================
# MEMORY MANAGER CONTRACT
# ============================================================

print("\n" + "=" * 100)
print("14. MEMORY MANAGER ↔ SEMANTIC MEMORY CONTRACT")
print("=" * 100)

try:

    from core.memory.memory_manager import MemoryManager

    print("✔ MemoryManager imported")

    print("\nMemoryManager methods referencing SemanticMemory-like APIs:")

    source = inspect.getsource(MemoryManager)

    interesting = [
        "semantic.",
        "self.semantic",
        "restore(",
        "find_by_subject",
        "find_by_tag",
        "hybrid_search",
        "semantic_search",
        "remember",
        "forget",
    ]

    for i, line in enumerate(source.splitlines(), 1):

        if any(x in line for x in interesting):

            print(
                f"{i:5}: {line}"
            )

except Exception as e:

    print("❌ MemoryManager inspection failed")
    print(repr(e))


# ============================================================
# BRAIN CONTRACT
# ============================================================

print("\n" + "=" * 100)
print("15. BRAIN MEMORY / LEARNING CONTRACT")
print("=" * 100)

try:

    from core.orchestration.brain import Brain

    source = inspect.getsource(Brain)

    targets = [
        "build_context",
        "memory.",
        "semantic.",
        "_extract_fact",
        "auto_accept",
        "experience",
        "knowledge",
        "remember_knowledge",
        "learn",
    ]

    for i, line in enumerate(source.splitlines(), 1):

        if any(x in line for x in targets):

            print(
                f"{i:5}: {line}"
            )

except Exception as e:

    print("❌ Brain inspection failed")
    print(repr(e))


# ============================================================
# FINAL SUMMARY
# ============================================================

print("\n" + "=" * 100)
print(" FORENSIC COMPLETE")
print("=" * 100)

print("""
NO WRITE OPERATIONS WERE PERFORMED.

The script did NOT:
  - INSERT
  - UPDATE
  - DELETE
  - COMMIT
  - clear()
  - forget()
  - remember()
  - rebuild FAISS
  - save FAISS

IMPORTANT:
Send the COMPLETE terminal output.

Especially do NOT remove:
  [10. RAW FAISS SEARCH]
  [11. SEMANTIC_SEARCH]
  [12. HYBRID_SEARCH]
  [14. MEMORY MANAGER CONTRACT]
  [15. BRAIN CONTRACT]

Those sections will let us identify the exact failing function/contract.
""")

try:
    conn.close()
except:
    pass
