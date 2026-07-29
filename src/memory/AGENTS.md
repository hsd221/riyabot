# src/memory - Persistent Memory and Retrieval

## OVERVIEW
This package stores and retrieves long-lived memory, atom associations, trace chains, learned profiles, and vector-backed evidence. It is a persistence boundary, not a general chat utility package.

## WHERE TO LOOK
| Task | Location | Notes |
|---|---|---|
| SQLite models and initialization | `schema.py` | Memory tables and database setup. |
| Unified persistence/vector access | `store.py` | `MemoryStore`, `QdrantManager`, vector profile and migration lifecycle. |
| Write/recovery semantics | `write_ops.py`, `trace_chain.py` | Preserve operation ordering, recovery, and transaction result accuracy. |
| Atom and association behavior | `atom.py`, `atom_association.py` | Persistent memory units and relationship construction. |
| Encoding and retrieval | `encoding_pipeline.py`, `layer*_*.py`, `bm25_retrieval.py` | Keep retrieval paths and candidate handling bounded. |
| Reconciliation and decay | `reconciliation.py`, `forgetting.py`, `conflict_arbitration.py` | State transitions require explicit persistence semantics. |
| Vector migration | `vector_migration.py` | Coordinates profile changes with the store. |

## PERSISTENCE CONTRACTS
- SQLite is the source of truth; Qdrant is an optional index. A vector failure must not silently corrupt, erase, or falsely report source-data writes.
- Reuse `MemoryStore` and `QdrantManager` for memory persistence and vector work; do not open a parallel SQLite/Qdrant client or create an independent index lifecycle.
- Keep Qdrant collection aliases, embedding signatures, dimensions, and persisted `VectorIndexState` coherent. Do not manually rename a live collection or bypass `QdrantManager` migration flow.
- Treat cache and WAL/recovery state as durable correctness mechanisms. Preserve ordering, rollback counts, and restart recovery when changing writes.
- IDs, payload fields, and privacy/source metadata are persistence contracts. Add migrations or compatibility handling before changing stored shapes.
- Bound caches and candidate lists; remove reverse references when their owning cache entry is evicted.

## ANTI-PATTERNS
- Do not assume Qdrant is installed or reachable; retain existing graceful-degradation paths.
- Do not mark a batch as successful before its transactional/persistent write succeeds.
- Do not mutate a vector/profile configuration in place while an index migration is active.
- Do not send raw private memory, database errors, or vector credentials into logs or model prompts.

## VERIFICATION
```bash
uv run python -m unittest tests.test_memory_store tests.test_memory_write_ops
uv run python -m unittest tests.test_memory_trace_chain tests.test_atom_association
```

Add focused regression coverage for changed recovery, transaction, cache, index, or retrieval behavior.
