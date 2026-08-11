"""Pydantic models for YouTube SEO packs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class YoutubeChapter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_seconds: int = Field(ge=0)
    label: str = Field(min_length=1, max_length=80)


class YoutubePack(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    mode: Literal["shorts", "longform"]
    language: str = "en"
    primary_title: str = Field(min_length=1, max_length=120)
    alt_titles: list[str] = Field(default_factory=list, max_length=5)
    description: str = Field(min_length=1, max_length=5000)
    tags: list[str] = Field(default_factory=list, max_length=30)
    hashtags: list[str] = Field(default_factory=list, max_length=15)
    pinned_comment: str = Field(default="", max_length=500)
    chapters: list[YoutubeChapter] = Field(default_factory=list, max_length=20)
    source: Literal["llm", "fallback"] = "fallback"
    generated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @field_validator("hashtags", mode="before")
    @classmethod
    def _normalize_hashtags(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        out: list[str] = []
        for item in value:
            text = str(item or "").strip()
            if not text:
                continue
            if not text.startswith("#"):
                text = f"#{text.lstrip('#')}"
            out.append(text)
        return out

    @field_validator("alt_titles", "tags", mode="before")
    @classmethod
    def _strip_string_list(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        return [str(item).strip() for item in value if str(item).strip()]
