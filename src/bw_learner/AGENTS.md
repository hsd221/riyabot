# src/bw_learner - Behavior and Expression Learning

## OVERVIEW
This package derives behavior, expressions, jargon, and historical learning signals from chat data. It consumes recorded history and produces learned state; durable memory storage remains in `src/memory/`.

## WHERE TO LOOK
| Task | Location | Notes |
|---|---|---|
| Behavior lifecycle | `behavior_learner.py`, `behavior_selector.py`, `behavior_store.py` | Learning, selection, and persistence boundary. |
| Expression lifecycle | `expression_learner.py`, `expression_selector.py`, `expression_reflector.py` | Generate, evaluate, and select expressions. |
| Expression vectors | `expression_vector_index.py` | Keep cache/index failures from aborting candidate processing. |
| Historical input | `history_import.py`, `history_learning.py`, `history_candidates.py`, `history_enrichment.py` | Normalize and enrich before learning. |
| Message ingestion | `message_recorder.py` | Entry point for learnable chat records. |
| Jargon | `jargon_miner.py`, `jargon_explainer.py` | Extract and explain group-specific language. |

## CONVENTIONS
- Keep behavior learning, expression learning, and message recording separate; do not move chat orchestration into this package.
- Treat message history and model-produced analyses as untrusted input. Preserve existing validation, filtering, and bounded candidate selection.
- Cache/vector writes are enrichments: log and degrade safely when they fail, while preserving the primary learner result where existing behavior permits it.
- Preserve stored behavior/expression identifiers and database shape unless a compatibility plan accompanies the change.

## ANTI-PATTERNS
- Do not turn failed enrichment into false learner success counts.
- Do not let one malformed historical record terminate a whole import or candidate batch without the existing error policy.
- Do not use private message content in broad logs or diagnostics.

## VERIFICATION
Run the focused learner tests matching the changed subsystem, then add a `tests/test_<area>.py` regression test for changed history, selection, or persistence behavior.
