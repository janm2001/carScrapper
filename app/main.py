from __future__ import annotations

import json
import hashlib
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.staticfiles import StaticFiles

from .models import Listing, ManualListingInput, SearchFilters, SearchResponse, SourceName, SourceStatus
from .market import enrich_listings_from_cache, refresh_market_cache_for_listings
from .scoring import filter_and_rank


ROOT = Path(__file__).resolve().parent.parent
MANUAL_PATH = ROOT / "data" / "manual_listings.json"
MARKET_CACHE_PATH = ROOT / "data" / "market_cache.json"

app = FastAPI(title="EV Deal Scout")


@app.get("/api/search", response_model=SearchResponse)
async def search(
    min_price: int = Query(5000, ge=0),
    max_price: int = Query(12000, ge=0),
    max_mileage: int | None = Query(None, ge=0),
    sources: str = Query("manual"),
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

    if refresh:
        await refresh_market_cache_for_listings(_read_manual(), MARKET_CACHE_PATH)

    raw_listings = enrich_listings_from_cache(_read_manual(), MARKET_CACHE_PATH)
    ranked = filter_and_rank(raw_listings, filters)
    refreshed = sum(1 for item in raw_listings if item.market_status == "ok")
    statuses = [
        SourceStatus(
            source="manual",
            ok=bool(raw_listings),
            message="Loaded saved manual listings." if raw_listings else "No manual listings saved yet.",
            fetched=len(raw_listings),
        ),
        SourceStatus(
            source="autoscout24",
            ok=refreshed > 0,
            message=(
                "Using cached AutoScout24 market comparisons."
                if refreshed
                else "Market data is empty or stale. Use Refresh market prices."
            ),
            fetched=refreshed,
        ),
    ]

    return SearchResponse(listings=ranked, statuses=statuses)


@app.post("/api/manual-listings", response_model=Listing)
async def add_manual_listing(payload: ManualListingInput) -> Listing:
    title = payload.title or _default_title(payload)
    listing = Listing(
        id=f"manual-{hashlib.sha1(f'{payload.url}|{payload.make}|{payload.model}|{payload.year}'.encode('utf-8')).hexdigest()[:16]}",
        source="manual",
        title=title,
        url=payload.url,
        make=payload.make.strip(),
        model=payload.model.strip(),
        battery_kwh=payload.battery_kwh,
        trim=payload.trim.strip() if payload.trim else None,
        price_eur=payload.price_eur,
        mileage_km=payload.mileage_km,
        year=payload.year,
        location=payload.location,
        raw_text=f"{title} {payload.price_eur} EUR {payload.mileage_km} km",
    )
    listings = _read_manual()
    listings = [item for item in listings if item.id != listing.id]
    listings.append(listing)
    _write_json(MANUAL_PATH, listings)
    return listing


@app.post("/api/market-refresh")
async def refresh_market_prices() -> dict:
    listings = _read_manual()
    result = await refresh_market_cache_for_listings(listings, MARKET_CACHE_PATH)
    return {
        "updated": result.updated,
        "failed": result.failed,
        "messages": result.messages,
    }


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


app.mount("/", StaticFiles(directory=ROOT / "app" / "static", html=True), name="static")


def _parse_sources(value: str) -> list[SourceName]:
    allowed = {"manual", "autoscout24"}
    parsed = [part.strip() for part in value.split(",") if part.strip() in allowed]
    return parsed or ["manual"]


def _read_manual() -> list[Listing]:
    return _read_listing_file(MANUAL_PATH)


def _read_listing_file(path: Path) -> list[Listing]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [_upgrade_listing(item) for item in data]
    except (json.JSONDecodeError, OSError, ValueError):
        return []


def _write_json(path: Path, listings: list[Listing]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [item.model_dump(mode="json") for item in listings]
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _upgrade_listing(item: dict) -> Listing:
    if not item.get("make") or not item.get("model"):
        make, model = _infer_make_model(str(item.get("title", "")))
        item["make"] = item.get("make") or make
        item["model"] = item.get("model") or model
    return Listing.model_validate(item)


def _infer_make_model(title: str) -> tuple[str | None, str | None]:
    lowered = title.lower()
    known_models = {
        "renault": ("zoe", "twingo"),
        "smart": ("fortwo", "forfour"),
        "nissan": ("leaf",),
        "bmw": ("i3",),
        "volkswagen": ("e-up", "id.3", "id3"),
        "vw": ("e-up", "id.3", "id3"),
        "hyundai": ("ioniq", "kona"),
        "kia": ("soul", "e-niro", "niro"),
        "dacia": ("spring",),
    }
    for make, models in known_models.items():
        if make not in lowered:
            continue
        for model in models:
            if model in lowered:
                normalized_make = "Volkswagen" if make == "vw" else make.title()
                normalized_model = "ID.3" if model == "id3" else model.title()
                return normalized_make, normalized_model
    return None, None


def _default_title(payload: ManualListingInput) -> str:
    extras = " ".join(part for part in (payload.trim, f"{payload.battery_kwh:g} kWh" if payload.battery_kwh else None) if part)
    return " ".join(part for part in (payload.make, payload.model, extras, str(payload.year)) if part)
