# src/llm_models - Model Clients, Payloads, and Embeddings

## OVERVIEW
This package adapts configured model providers for chat and embedding requests. It owns provider clients, request payload construction, errors, request tracing, and embedding-profile behavior.

## WHERE TO LOOK
| Task | Location | Notes |
|---|---|---|
| Provider client selection | `model_client/` | Provider-specific transport and response adaptation. |
| Request payload construction | `payload_content/` | Keep provider payload rules isolated here. |
| Embeddings | `embedding.py`, `embedding_profile.py` | Model-space identity is consumed by memory indexing. |
| Tracing | `request_trace.py` | Request lifecycle diagnostics; preserve redaction. |
| Shared helpers/errors | `utils.py`, `utils_model.py`, `exceptions.py` | Reuse established normalization and exception contracts. |

## CONTRACTS
- Treat configured model descriptors as request inputs, not mutable global state. Copy/derive request-specific options such as search capability instead of modifying a shared `ModelInfo`.
- Keep provider API keys, authorization headers, raw upstream bodies, and prompt contents out of logs and exception text.
- Validate/normalize provider responses at the client boundary; callers should receive established result and exception shapes.
- An embedding profile change is coupled to `src/memory/` vector migration. Do not change signature or dimension semantics independently.

## ANTI-PATTERNS
- Do not add provider-specific conditionals to chat orchestration when they belong in `model_client/` or `payload_content/`.
- Do not translate upstream authentication failures into a local WebUI-session failure; preserve the backend's existing error boundary.
- Do not retry non-idempotent or streamed requests without an explicit existing policy.

## VERIFICATION
Run focused tests for the changed provider, payload, embedding, or trace path. Exercise failure redaction and immutable per-request options when touching client configuration.
