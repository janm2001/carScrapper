from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, median
from urllib.parse import quote, urljoin, urlencode

import httpx
from bs4 import BeautifulSoup

from .models import Listing


HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,hr;q=0.8",
    "User-Agent": "Mozilla/5.0 EVDealScout/0.2 (+local personal market research)",
}

CACHE_TTL = timedelta(hours=24)
MAX_PAGES = 3
REQUEST_DELAY_SECONDS = 1.0
AUTOSCOUT_BASE = "https://www.autoscout24.com"


@dataclass
class MarketListing:
    price_eur: int
    mileage_km: int | None
    first_registration_year: int | None
    location: str | None
    url: str | None
    image_url: str | None


@dataclass
class MarketStats:
    average_price_eur: int | None = None
    median_price_eur: int | None = None
    sample_size: int = 0
    min_price_eur: int | None = None
    max_price_eur: int | None = None
    source_url: str | None = None
    status: str = "not_checked"


@dataclass
class MarketRefreshResult:
    updated: int = 0
    failed: int = 0
    messages: list[str] = field(default_factory=list)


def build_autoscout24_url(make: str, model: str, year: int, page: int = 1) -> str:
    params = {
        "sort": "standard",
        "desc": "0",
        "ustate": "N,U",
        "atype": "C",
        "fregfrom": str(year),
        "fregto": str(year),
    }
    if page > 1:
        params["page"] = str(page)

    make_slug = _slug(make)
    model_slug = _slug(model)
    return f"{AUTOSCOUT_BASE}/lst/{make_slug}/{model_slug}/ft_electric?{urlencode(params)}"


def parse_autoscout24_html(html: str) -> list[MarketListing]:
    soup = BeautifulSoup(html, "html.parser")
    script = soup.find("script", id="__NEXT_DATA__")
    if script is None or not script.string:
        return []

    try:
        data = json.loads(script.string)
    except json.JSONDecodeError:
        return []

    page_props = data.get("props", {}).get("pageProps", {})
    listings = page_props.get("listings", [])
    if not isinstance(listings, list):
        return []

    parsed: list[MarketListing] = []
    for item in listings:
        if not isinstance(item, dict):
            continue
        listing = _parse_market_listing(item)
        if listing is not None:
            parsed.append(listing)
    return parsed


def compute_market_stats(listings: list[MarketListing], source_url: str | None = None) -> MarketStats:
    prices = [item.price_eur for item in listings if item.price_eur > 0]
    if not prices:
        return MarketStats(source_url=source_url, status="no_market_listings")

    return MarketStats(
        average_price_eur=round(mean(prices)),
        median_price_eur=round(median(prices)),
        sample_size=len(prices),
        min_price_eur=min(prices),
        max_price_eur=max(prices),
        source_url=source_url,
        status="ok",
    )


def apply_market_stats(listing: Listing, stats: MarketStats) -> Listing:
    listing.market_average_price_eur = stats.average_price_eur
    listing.market_median_price_eur = stats.median_price_eur
    listing.market_sample_size = stats.sample_size
    listing.market_min_price_eur = stats.min_price_eur
    listing.market_max_price_eur = stats.max_price_eur
    listing.market_source_url = stats.source_url
    listing.market_status = stats.status

    if listing.price_eur is not None and stats.median_price_eur:
        listing.market_delta_eur = listing.price_eur - stats.median_price_eur
        listing.market_delta_pct = round((listing.market_delta_eur / stats.median_price_eur) * 100, 1)
    else:
        listing.market_delta_eur = None
        listing.market_delta_pct = None
    return listing


def enrich_listings_from_cache(listings: list[Listing], cache_path: Path) -> list[Listing]:
    cache = _read_market_cache(cache_path)
    for listing in listings:
        stats = _cached_stats_for_listing(listing, cache)
        if stats is not None:
            apply_market_stats(listing, stats)
        elif _has_market_identity(listing):
            _clear_market_stats(listing)
            listing.market_source_url = build_autoscout24_url(listing.make or "", listing.model or "", listing.year or 0)
            listing.market_status = "needs_refresh"
        else:
            _clear_market_stats(listing)
            listing.market_status = "missing_make_model_year"
    return listings


async def refresh_market_cache_for_listings(listings: list[Listing], cache_path: Path) -> MarketRefreshResult:
    cache = _read_market_cache(cache_path)
    groups: dict[str, Listing] = {}
    for listing in listings:
        if _has_market_identity(listing):
            groups[_cache_key(listing.make or "", listing.model or "", listing.year or 0)] = listing

    result = MarketRefreshResult()
    if not groups:
        result.messages.append("No saved manual listings have make, model, and year.")
        return result

    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=25) as client:
        for listing in groups.values():
            stats, error = await _fetch_market_stats(client, listing.make or "", listing.model or "", listing.year or 0)
            key = _cache_key(listing.make or "", listing.model or "", listing.year or 0)
            cache[key] = {
                "make": listing.make,
                "model": listing.model,
                "year": listing.year,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "stats": stats.__dict__,
            }
            if error:
                result.failed += 1
                result.messages.append(f"{listing.make} {listing.model} {listing.year}: {error}")
            else:
                result.updated += 1
                result.messages.append(
                    f"{listing.make} {listing.model} {listing.year}: {stats.sample_size} AutoScout24 listings."
                )

            await asyncio.sleep(REQUEST_DELAY_SECONDS)

    _write_market_cache(cache_path, cache)
    return result


async def _fetch_market_stats(
    client: httpx.AsyncClient,
    make: str,
    model: str,
    year: int,
) -> tuple[MarketStats, str | None]:
    all_listings: list[MarketListing] = []
    first_url = build_autoscout24_url(make, model, year)

    for page in range(1, MAX_PAGES + 1):
        url = build_autoscout24_url(make, model, year, page=page)
        try:
            response = await client.get(url)
        except httpx.HTTPError as exc:
            return MarketStats(source_url=first_url, status="request_failed"), exc.__class__.__name__

        if response.status_code >= 400:
            return MarketStats(source_url=first_url, status=f"http_{response.status_code}"), f"HTTP {response.status_code}"

        page_listings = parse_autoscout24_html(response.text)
        if not page_listings:
            break
        all_listings.extend(page_listings)

    stats = compute_market_stats(all_listings, first_url)
    if stats.sample_size == 0:
        return stats, "No market listings found"
    return stats, None


def _parse_market_listing(item: dict) -> MarketListing | None:
    price = _extract_price(item)
    if price is None:
        return None

    details = _details_by_label(item.get("vehicleDetails", []))
    mileage = _parse_int(details.get("Mileage"))
    first_registration_year = _parse_year(details.get("First registration"))
    location = _extract_location(item)
    url = _extract_url(item)
    image_url = _extract_image_url(item)

    return MarketListing(
        price_eur=price,
        mileage_km=mileage,
        first_registration_year=first_registration_year,
        location=location,
        url=url,
        image_url=image_url,
    )


def _clear_market_stats(listing: Listing) -> None:
    listing.market_average_price_eur = None
    listing.market_median_price_eur = None
    listing.market_sample_size = 0
    listing.market_min_price_eur = None
    listing.market_max_price_eur = None
    listing.market_delta_eur = None
    listing.market_delta_pct = None
    listing.market_source_url = None


def _extract_price(item: dict) -> int | None:
    price = item.get("price")
    if isinstance(price, dict):
        for key in ("priceFormatted", "formatted", "amount", "raw"):
            value = price.get(key)
            if isinstance(value, int):
                return value
            if isinstance(value, str):
                parsed = _parse_int(value)
                if parsed is not None:
                    return parsed
    return None


def _details_by_label(details: object) -> dict[str, str]:
    parsed: dict[str, str] = {}
    if not isinstance(details, list):
        return parsed
    for detail in details:
        if not isinstance(detail, dict):
            continue
        label = detail.get("ariaLabel") or detail.get("label")
        value = detail.get("text") or detail.get("value") or detail.get("data")
        if isinstance(label, str) and value is not None:
            parsed[label] = str(value)
    return parsed


def _extract_location(item: dict) -> str | None:
    location = item.get("location")
    if isinstance(location, str):
        return location
    if isinstance(location, dict):
        parts = [
            location.get("city"),
            location.get("zip"),
            location.get("country"),
            location.get("countryCode"),
        ]
        cleaned = [str(part) for part in parts if part]
        return ", ".join(cleaned) if cleaned else None
    return None


def _extract_url(item: dict) -> str | None:
    value = item.get("url") or item.get("detailPageUrl")
    if not isinstance(value, str) or not value:
        return None
    return urljoin(AUTOSCOUT_BASE, value)


def _extract_image_url(item: dict) -> str | None:
    images = item.get("images")
    if not isinstance(images, list) or not images:
        return None
    first = images[0]
    if isinstance(first, str):
        return first
    if isinstance(first, dict):
        for key in ("src", "url", "imageUrl"):
            value = first.get(key)
            if isinstance(value, str):
                return value
    return None


def _cached_stats_for_listing(listing: Listing, cache: dict) -> MarketStats | None:
    if not _has_market_identity(listing):
        return None
    key = _cache_key(listing.make or "", listing.model or "", listing.year or 0)
    entry = cache.get(key)
    if not isinstance(entry, dict) or _is_cache_stale(entry.get("fetched_at")):
        return None
    stats = entry.get("stats")
    if not isinstance(stats, dict):
        return None
    return MarketStats(**stats)


def _read_market_cache(cache_path: Path) -> dict:
    if not cache_path.exists():
        return {}
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_market_cache(cache_path: Path, cache: dict) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def _is_cache_stale(fetched_at: object) -> bool:
    if not isinstance(fetched_at, str):
        return True
    try:
        fetched = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    return datetime.now(timezone.utc) - fetched > CACHE_TTL


def _has_market_identity(listing: Listing) -> bool:
    return bool(listing.make and listing.model and listing.year)


def _cache_key(make: str, model: str, year: int) -> str:
    return f"{_slug(make)}:{_slug(model)}:{year}"


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return quote(slug)


def _parse_int(value: str | None) -> int | None:
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    return int(digits) if digits else None


def _parse_year(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"(19|20)\d{2}", value)
    if not match:
        return None
    year = int(match.group(0))
    return year if 1990 <= year <= 2030 else None
