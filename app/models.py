from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


SourceName = Literal["njuskalo", "index_oglasi", "manual", "autoscout24"]


class SearchFilters(BaseModel):
    min_price: int = Field(default=5000, ge=0)
    max_price: int = Field(default=12000, ge=0)
    max_mileage: int | None = Field(default=None, ge=0)
    sources: list[SourceName] = Field(default_factory=lambda: ["manual", "autoscout24"])
    refresh: bool = False


class Listing(BaseModel):
    id: str
    source: SourceName
    title: str
    url: str
    make: str | None = None
    model: str | None = None
    battery_kwh: float | None = None
    trim: str | None = None
    price_eur: int | None = None
    mileage_km: int | None = None
    year: int | None = None
    location: str | None = None
    image_url: str | None = None
    posted_at: str | None = None
    scraped_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    raw_text: str = ""
    score: float | None = None
    rank: int | None = None
    value_index: float | None = None
    negotiation_open_eur: int | None = None
    negotiation_ceiling_eur: int | None = None
    reasons: list[str] = Field(default_factory=list)
    market_average_price_eur: int | None = None
    market_median_price_eur: int | None = None
    market_sample_size: int = 0
    market_min_price_eur: int | None = None
    market_max_price_eur: int | None = None
    market_delta_eur: int | None = None
    market_delta_pct: float | None = None
    market_source_url: str | None = None
    market_status: str = "not_checked"


class ManualListingInput(BaseModel):
    make: str = Field(min_length=1)
    model: str = Field(min_length=1)
    year: int = Field(ge=1990, le=2030)
    url: str = Field(min_length=4)
    price_eur: int = Field(ge=0)
    mileage_km: int = Field(ge=0)
    title: str | None = Field(default=None, min_length=2)
    battery_kwh: float | None = Field(default=None, ge=0)
    trim: str | None = None
    location: str | None = None


class SourceStatus(BaseModel):
    source: SourceName
    ok: bool
    message: str
    fetched: int = 0


class SearchResponse(BaseModel):
    listings: list[Listing]
    statuses: list[SourceStatus]
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
