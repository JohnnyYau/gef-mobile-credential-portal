"""Pydantic request models for the portal API."""

from typing import Any

from pydantic import BaseModel, ConfigDict


class IssueBody(BaseModel):
    """A full credential document to issue on the chain.

    Must contain PersonalParticulars, AcademicInfo and DocumentInfo.
    """
    document: dict
    student_email: str | None = None  # for the email notifier (dry-run by default)


class BatchIssueItem(BaseModel):
    """One credential row in a batch-issue request.

    ``document`` is validated per-row inside the endpoint (not by Pydantic)
    so a malformed row is reported per-row instead of failing the whole batch.
    """

    document: Any = None
    student_email: str | None = None


class IssueBatchBody(BaseModel):
    """Up to ``BATCH_ISSUE_MAX`` credentials in one admin request.

    Rows are processed independently: a bad row is reported per-row and
    does not roll back the rows that succeeded.
    """

    credentials: list[BatchIssueItem]


class AddSignerBody(BaseModel):
    """Register a new trusted data signer for this chain."""

    name: str = "NEW SIGNER"
    ds_algo: str = "ML_DSA_65"


class ActiveSignerBody(BaseModel):
    """Switch which registered signer issues blocks."""

    sha256fgpt: str


class RetireSignerBody(BaseModel):
    """Retire a signer: keep its pre-retirement blocks valid, stop trusting new
    ones. The entry and the public key stay in the registry (U16)."""

    sha256fgpt: str


class RevokeBody(BaseModel):
    """Either the on-chain hash or the full document (hash is derived).

    ``reason`` and ``effective_at`` (unix seconds) are optional; when present
    they are recorded on the REVOKE block, surfaced on verdicts and included
    in the signed revocation status list.
    """

    hashed_document: str | None = None
    document: dict | None = None
    reason: str | None = None
    effective_at: float | None = None


class ChatBody(BaseModel):
    """A natural-language question for the RAG assistant.

    ``session_id`` anchors "the person in context" across follow-ups
    ("what degree does he hold?"). ``web`` forces web research for the
    person even when the question has no explicit web keyword.
    """

    question: str
    session_id: str | None = None
    web: bool | None = None


class CustomBuildBody(BaseModel):
    """Self-service credential draft for ``POST /api/custom/build``.

    Every field is typed ``Any`` and unknown keys are allowed on purpose: the
    previous implementation handed the raw JSON object straight to
    ``custom_service.build_document``, which reads values with ``dict.get``
    and normalises them itself (``_clean`` / ``_norm_date``). Declaring
    ``str`` here would newly reject numbers or booleans that used to be
    accepted, so the model documents the accepted keys without tightening
    them. ``issue`` keeps the raw value for the same reason (its truthiness
    decides whether the credential is put on the chain).
    """

    model_config = ConfigDict(extra="allow")

    surname: Any = None
    given_names: Any = None
    name: Any = None
    student_id: Any = None
    dob: Any = None
    sex: Any = None
    degree: Any = None
    degree_start: Any = None
    degree_end: Any = None
    honour: Any = None
    observations: Any = None
    issuer: Any = None
    issuer_unit: Any = None
    doc_type: Any = None
    date_of_issue: Any = None
    authorized_signature: Any = None
    issue: Any = True


class VerifyDocumentBody(BaseModel):
    """JSON form of ``POST /api/verify/document``: ``{"document": {...}}``.

    The multipart form branch keeps its existing file handling.
    """

    document: dict


class VerifyBatchBody(BaseModel):
    """Employer-pack batch verify body: ``{"hashes": [...]}``.

    Elements stay ``Any`` so a non-string row is reported per row (as an
    ``ERROR`` entry) instead of failing the whole request — that per-row
    tolerance is part of the endpoint's existing contract.
    """

    hashes: list[Any]


class ApiKeyCreateBody(BaseModel):
    """Body of ``POST /api/admin/apikeys``.

    ``name`` stays ``Any`` because the previous implementation passed the raw
    value through with ``payload.get("name") or "unnamed"``.

    ``expires_in_days`` is additive (batch U3.2): omitted/0 keeps a
    non-expiring key, exactly like before this field existed.
    """

    name: Any = None
    expires_in_days: Any = None


class DiscloseBody(BaseModel):
    """Body of ``POST /api/disclose/{hashed_document}`` (batch U4.4).

    ``hide_sections`` and ``hide_fields`` are optional; omitted means the
    default hidden section (PersonalParticulars).
    """

    hide_sections: Any = None
    hide_fields: Any = None
