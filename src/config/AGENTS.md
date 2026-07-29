# src/config - Typed Configuration Definitions and Generation

## OVERVIEW
This package defines Python configuration schemas, parses and validates TOML, and generates/upgrades runtime configuration. `config/` at repository root is generated runtime state, not the source of truth.

## WHERE TO LOOK
| Task | Location | Notes |
|---|---|---|
| Base schema/parsing | `config_base.py` | Typed fields, validation, TOML conversion. |
| Global configuration | `config.py` | Runtime configuration aggregation. |
| Core defaults | `official_configs.py` | Canonical configuration definitions. |
| API/adapter configuration | `api_ada_configs.py` | Adapter-facing configuration schemas. |
| Generation and upgrades | `config_generation.py` | Creation, updates, and atomic persistence. |

## CONFIGURATION CONTRACTS
- Change Python definitions first; do not hand-maintain generated root `config/*.toml` as source.
- Reuse `Config`, `update_config()`, `update_model_config()`, and existing parsing helpers; do not add a parallel TOML loader/writer.
- Preserve forward/backward compatibility and unknown-field handling where present. Schema changes need an explicit migration/upgrade path.
- Distinguish fixed tuples from variadic tuples (`tuple[T, ...]`) during type-driven parsing; do not infer fixed arity from a variadic annotation.
- Write TOML atomically: generate/validate a replacement and replace only after the full write succeeds. Never truncate an existing configuration before a replacement is ready.
- Reuse the existing secure-directory, regular-file, bounded-read, and atomic-write helpers in `config.py`; they enforce path, symlink, size, and permission checks.
- Keep secrets masked in repr/logging and out of test fixtures committed to the repository.

## ANTI-PATTERNS
- Do not validate paths, URLs, or values with ad hoc string checks when shared configuration/TOML helpers already define behavior.
- Do not silently discard a malformed user value if existing validation can report its field-level cause.
- Do not couple a config schema change to an unrelated runtime refactor.

## VERIFICATION
Add focused `unittest` coverage for parsing, round trips, tuple annotations, upgrade compatibility, and failed-write preservation whenever changing schema or generation behavior.
