"""Pydantic request models for the portal API."""

from typing import Any, List, Optional

from pydantic import BaseModel


class IssueBody(BaseModel):
    """A full credential document to issue on the chain.

    Must contain PersonalParticulars, AcademicInfo and DocumentInfo.
    """
    document: dict
    student_email: Optional[str] = None  # for the email notifier (dry-run by default)


class BatchIssueItem(BaseModel):
    """One credential row in a batch-issue request.

    ``document`` is validated per-row inside the endpoint (not by Pydantic)
    so a malformed row is reported per-row instead of failing the whole batch.
    """

    document: Any = None
    student_email: Optional[str] = None


class IssueBatchBody(BaseModel):
    """Up to ``BATCH_ISSUE_MAX`` credentials in one admin request.

    Rows are processed independently: a bad row is reported per-row and
    does not roll back the rows that succeeded.
    """

    credentials: List[BatchIssueItem]


class AddSignerBody(BaseModel):
    """Register a new trusted data signer for this chain."""

    name: str = "NEW SIGNER"
    ds_algo: str = "ML_DSA_65"


class ActiveSignerBody(BaseModel):
    """Switch which registered signer issues blocks."""

    sha256fgpt: str


class RevokeBody(BaseModel):
    """Either the on-chain hash or the full document (hash is derived).

    ``reason`` and ``effective_at`` (unix seconds) are optional; when present
    they are recorded on the REVOKE block, surfaced on verdicts and included
    in the signed revocation status list.
    """

    hashed_document: Optional[str] = None
    document: Optional[dict] = None
    reason: Optional[str] = None
    effective_at: Optional[float] = None


class ChatBody(BaseModel):
    """A natural-language question for the RAG assistant.

    ``session_id`` anchors "the person in context" across follow-ups
    ("what degree does he hold?"). ``web`` forces web research for the
    person even when the question has no explicit web keyword.
    """

    question: str
    session_id: Optional[str] = None
    web: Optional[bool] = None
