"""Contratos explícitos: desconocido no equivale a cero ni a un hecho realizado."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SimilarEventRequest(Model):
    description: str = Field(min_length=3, max_length=4000)
    event_type: str | None = Field(default=None, max_length=150)
    attendees: int | None = Field(default=None, ge=1, le=1_000_000)
    location: str | None = Field(default=None, max_length=200)


class EvidenceFragment(Model):
    id: str
    source_id: str
    chunk_index: int | None = None
    file_name: str
    sheet_tab: str | None = None
    text: str
    drive_url: str | None = None


class Citation(Model):
    evidence_id: str
    quote: str = Field(min_length=1)


class SupportedFact(Model):
    text: str = Field(min_length=1)
    citations: list[Citation] = Field(min_length=1)


class HistoricalCost(Model):
    amount_text: str
    currency: str | None = None
    date_text: str | None = None
    scope: str | None = None
    citations: list[Citation] = Field(min_length=1)


class CandidateEvent(Model):
    event_name: str = Field(min_length=1)
    identity_citations: list[Citation] = Field(min_length=1)


class CandidateEvents(Model):
    events: list[CandidateEvent] = Field(default_factory=list, max_length=8)


class SimilarEventMatch(CandidateEvent):
    event_date: date | None = None
    date_citations: list[Citation] = Field(default_factory=list)
    status: Literal["completed", "planned", "ongoing", "cancelled", "unknown"] = "unknown"
    status_citations: list[Citation] = Field(default_factory=list)
    characteristics: list[SupportedFact] = Field(default_factory=list)
    similarities: list[SupportedFact] = Field(default_factory=list)
    differences: list[SupportedFact] = Field(default_factory=list)
    suppliers: list[SupportedFact] = Field(default_factory=list)
    costs: list[HistoricalCost] = Field(default_factory=list)
    lessons: list[SupportedFact] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    suggestions: list[SupportedFact] = Field(default_factory=list)


class Synthesis(Model):
    events: list[SimilarEventMatch] = Field(default_factory=list, max_length=5)


class SimilarEventResult(Synthesis):
    criteria: SimilarEventRequest
    evidence: list[EvidenceFragment] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
