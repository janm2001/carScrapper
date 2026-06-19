from __future__ import annotations

import json
import hashlib
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.staticfiles import StaticFiles

from .models import Listing, ManualListingInput, SearchFilters, SearchResponse, SourceName, SourceStatus
from .scoring import filter_and_rank
from .scrapers import scrape_sources


ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = ROOT / "data" / "cache.json"
MANUAL_PATH = ROOT / "data" / "manual_listings.json"

app = FastAPI(title="EV Deal Scout")


@app.get("/api/search", response_model=SearchResponse)
async def search(
    min_price: int = Query(5000, ge=0),
    max_price: int = Query(12000, ge=0),
    max_mileage: int | None = Query(None, ge=0),
    sources: str = Query("njuskalo,index_oglasi"),
    refresh: bool = Query(False),
) -> SearchResponse:
    selected_sources = _parse_sources(sources)
    filters = SearchFilters(
        min_price=min_price,
        max_price=max_price,
        max_mileage=max_mileage,
        sources=selected_sources,
        refresh=refresh,
    )

    raw_listings: list[Listing] = []
    statuses: list[SourceStatus] = []
    manual = _read_manual()
    raw_listings.extend(manual)

    if not refresh:
        cached = _read_cache()
        raw_listings.extend(cached)

    if refresh or not raw_listings:
        scraped, statuses = await scrape_sources(selected_sources)
        raw_listings.extend(scraped)
        if scraped:
            _write_cache(scraped)

    ranked = filter_and_rank(raw_listings, filters)
    if not statuses:
        statuses.append(
            SourceStatus(
                source="manual",
                ok=bool(raw_listings),
                message="Using local cached/manual listings. Use refresh to scrape again.",
                fetched=len(raw_listings),
            )
        )
    elif manual:
        statuses.append(
            SourceStatus(
                source="manual",
                ok=True,
                message="Loaded local manual listings.",
                fetched=len(manual),
            )
        )

    return SearchResponse(listings=ranked, statuses=statuses)


@app.post("/api/manual-listings", response_model=Listing)
async def add_manual_listing(payload: ManualListingInput) -> Listing:
    listing = Listing(
        id=f"manual-{hashlib.sha1(f'{payload.url}|{payload.title}'.encode('utf-8')).hexdigest()[:16]}",
        source="manual",
        title=payload.title,
        url=payload.url,
        price_eur=payload.price_eur,
        mileage_km=payload.mileage_km,
        year=payload.year,
        location=payload.location,
        raw_text=f"{payload.title} {payload.price_eur} EUR {payload.mileage_km} km",
    )
    listings = _read_manual()
    listings = [item for item in listings if item.id != listing.id]
    listings.append(listing)
    _write_json(MANUAL_PATH, listings)
    return listing


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


app.mount("/", StaticFiles(directory=ROOT / "app" / "static", html=True), name="static")


def _parse_sources(value: str) -> list[SourceName]:
    allowed = {"njuskalo", "index_oglasi", "manual"}
    parsed = [part.strip() for part in value.split(",") if part.strip() in allowed]
    return parsed or ["njuskalo", "index_oglasi"]


def _read_cache() -> list[Listing]:
    return _read_listing_file(CACHE_PATH)


def _read_manual() -> list[Listing]:
    return _read_listing_file(MANUAL_PATH)


def _read_listing_file(path: Path) -> list[Listing]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [Listing.model_validate(item) for item in data]
    except (json.JSONDecodeError, OSError, ValueError):
        return []


def _write_cache(listings: list[Listing]) -> None:
    _write_json(CACHE_PATH, listings)


def _write_json(path: Path, listings: list[Listing]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [item.model_dump(mode="json") for item in listings]
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
