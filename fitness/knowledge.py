"""Human-maintained, source-traceable knowledge entries for future RAG."""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Collection = Literal["training", "fat_loss", "supplements", "sleep_recovery"]
SourceType = Literal[
    "creator_opinion", "research_summary", "professional_guidance", "mixed"
]
EvidenceLevel = Literal["experience", "limited", "research", "guideline"]
ReviewStatus = Literal["pending", "approved", "rejected"]


class SourceVideo(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    bvid: str = Field(min_length=1, max_length=50)
    title: str = Field(min_length=1, max_length=500)
    url: str = Field(min_length=1, max_length=2000)
    published_at: str | None = Field(default=None, max_length=40)


class SourceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(min_length=1, max_length=200)
    creator_name: str = Field(min_length=1, max_length=200)
    video_url: str = Field(min_length=1, max_length=2000)
    video_title: str = Field(min_length=1, max_length=500)
    published_at: str | None = Field(default=None, max_length=40)
    transcript_path: str | None = Field(default=None, max_length=500)
    videos: list[SourceVideo] = Field(default_factory=list, max_length=20)


class KnowledgeItem(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(min_length=1, max_length=200)
    collection: Collection
    title: str = Field(min_length=1, max_length=300)
    claim: str = Field(min_length=1, max_length=2000)
    explanation: str | None = Field(default=None, max_length=4000)
    source_id: str = Field(min_length=1, max_length=200)
    source_type: SourceType
    evidence_level: EvidenceLevel
    review_status: ReviewStatus = "pending"
    review_note: str | None = Field(default=None, max_length=2000)
    timestamp_start: int | None = Field(default=None, ge=0)
    timestamp_end: int | None = Field(default=None, ge=0)
    tags: list[str] = Field(default_factory=list, max_length=20)
    safety_level: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def valid_timestamp(self):
        if (self.timestamp_start is not None and self.timestamp_end is not None
                and self.timestamp_start > self.timestamp_end):
            raise ValueError("timestamp_start cannot exceed timestamp_end")
        return self

    def embedding_text(self) -> str:
        parts = [self.title, self.claim]
        if self.explanation:
            parts.append(self.explanation)
        parts.extend(self.tags)
        return "\n".join(parts)


def _json_files(path: Path):
    return sorted(path.rglob("*.json")) if path.exists() else []


def load_knowledge(root: Path) -> list[KnowledgeItem]:
    """Load all item JSON files from the maintained collection folders."""
    result: list[KnowledgeItem] = []
    for collection in ("training", "fat_loss", "supplements", "sleep_recovery"):
        for path in _json_files(root / collection):
            payload = json.loads(path.read_text(encoding="utf-8"))
            values = payload if isinstance(payload, list) else [payload]
            result.extend(KnowledgeItem.model_validate(value) for value in values)
    return result


def load_sources(root: Path) -> dict[str, SourceRecord]:
    result = {}
    for path in _json_files(root / "sources"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        values = payload if isinstance(payload, list) else [payload]
        for value in values:
            source = SourceRecord.model_validate(value)
            if source.id in result:
                raise ValueError(f"duplicate source id: {source.id}")
            result[source.id] = source
    return result


def build_manifest(root: Path) -> list[dict]:
    """Return approved items enriched with their source; suitable for indexing."""
    sources = load_sources(root)
    manifest = []
    seen: set[str] = set()
    for item in load_knowledge(root):
        if item.id in seen:
            raise ValueError(f"duplicate knowledge id: {item.id}")
        seen.add(item.id)
        if item.source_id not in sources:
            raise ValueError(f"missing source for knowledge item: {item.id}")
        if item.review_status == "approved":
            manifest.append({"id": item.id, "collection": item.collection,
                             "title": item.title, "text": item.embedding_text(),
                             "source": sources[item.source_id].model_dump(mode="json"),
                             "metadata": item.model_dump(mode="json")})
    return manifest


def search_knowledge(root: Path, query: str, limit: int = 8) -> list[dict]:
    """Return simple explainable keyword matches from approved knowledge.

    This is deliberately a deterministic first RAG seam; embeddings can replace
    the scoring later without changing the returned document shape.
    """
    terms = [term.lower() for term in query.split() if term.strip()]
    if not terms:
        return []
    rows = build_manifest(root)
    scored = []
    for row in rows:
        haystack = f"{row['title']} {row['text']}".lower()
        score = sum(haystack.count(term) for term in terms)
        if score:
            scored.append((score, row))
    scored.sort(key=lambda pair: (-pair[0], pair[1]["id"]))
    return [row for _, row in scored[:limit]]
