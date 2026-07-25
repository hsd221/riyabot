"""API contracts for chat-history import routes."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


MAX_PARTICIPANT_SELECTION_OVERRIDES = 200


class ImportedChatResponse(BaseModel):
    name: str
    source_id: str
    chat_type: str
    self_user_id: str


class ImportedParticipantResponse(BaseModel):
    source_id: str
    name: str
    card: str
    message_count: int
    is_bot: bool


class ChatHistoryAnalysisResponse(BaseModel):
    source_format: str
    chat: ImportedChatResponse
    total_messages: int
    retained_messages: int
    filtered_messages: int
    noise_counts: dict[str, int]
    participants: list[ImportedParticipantResponse]
    participant_count: int = 0
    eligible_participant_count: int = 0
    start_timestamp: float | None
    end_timestamp: float | None
    total_window_count: int
    estimated_model_call_note: str = ""


class ChatHistoryImportProgress(BaseModel):
    stage: str
    current: int
    total: int


class ChatHistoryImportResume(BaseModel):
    can_resume: bool
    stage: str | None
    completed_windows: int
    attempt_count: int


class ChatHistoryImportResponse(BaseModel):
    import_id: str
    source_name: str
    source_size: int
    status: str
    chat_id: str | None
    analysis: ChatHistoryAnalysisResponse | None
    estimated_model_calls: dict[str, int]
    progress: ChatHistoryImportProgress
    resume: ChatHistoryImportResume
    options: dict[str, Any]
    result: dict[str, Any] | None
    error_message: str | None
    created_at: float
    updated_at: float
    started_at: float | None
    completed_at: float | None


class ChatHistoryImportListResponse(BaseModel):
    success: bool = True
    data: list[ChatHistoryImportResponse]


class ChatHistoryParticipantScopeRequest(BaseModel):
    mode: Literal["all", "custom"] = "all"
    included_ids: list[str] = Field(default_factory=list, max_length=MAX_PARTICIPANT_SELECTION_OVERRIDES)
    excluded_ids: list[str] = Field(default_factory=list, max_length=MAX_PARTICIPANT_SELECTION_OVERRIDES)


class ChatHistoryImportStartRequest(BaseModel):
    depth: Literal["fast", "balanced", "deep", "full"] = "balanced"
    participant_ids: list[str] = Field(default_factory=list, max_length=MAX_PARTICIPANT_SELECTION_OVERRIDES)
    participant_scope: ChatHistoryParticipantScopeRequest | None = None
    extract_memories: bool = False
    update_profiles: bool = False


class ChatHistoryImportDeleteResponse(BaseModel):
    success: bool
    message: str


class ChatHistoryParticipantPagination(BaseModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int


class ChatHistoryParticipantListResponse(BaseModel):
    data: list[ImportedParticipantResponse]
    pagination: ChatHistoryParticipantPagination


class ChatHistoryCandidatePagination(BaseModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int


class ChatHistoryCandidateListResponse(BaseModel):
    kind: Literal["expressions", "behaviors", "jargons", "memories", "profiles"]
    data: list[dict[str, Any]]
    pagination: ChatHistoryCandidatePagination


class ChatHistoryProfileDecisionRequest(BaseModel):
    decisions: dict[str, Literal["keep_existing", "apply_imported"]] = Field(
        default_factory=dict,
        max_length=100,
    )
