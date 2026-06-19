from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urlencode, urljoin

import httpx
from bs4 import BeautifulSoup

from .models import Listing, SourceStatus


HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
    "Accept-Language": "hr-HR,hr;q=0.9,en;q=0.8",
    "User-Agent": "Mozilla/5.0 EVDealScout/0.1 (+local personal research)",
}

EV_MODEL_PATHS = [
    "renault-zoe",
    "nissan-leaf",
    "bmw-i3",
    "smart-fortwo",
    "vw-e-up",
    "vw-id3",
    "hyundai-ioniq",
    "kia-soul",
    "dacia-spring",
    "citroen-c-zero",
    "peugeot-ion",
    "mitsubishi-i-miev",
]

EV_KEYWORDS = (
    "electric",
    "elektric",
    "struja",
    "ev",
    "zoe",
    "leaf",
    "i3",
    "e-up",
    "id.3",
    "ioniq",
    "soul",
    "spring",
    "c-zero",
    "i-miev",
)


@dataclass
class ScrapeResult:
    listings: list[Listing]
    status: SourceStatus


async def scrape_sources(sources: Iterable[str]) -> tuple[list[Listing], list[SourceStatus]]:
    listings: list[Listing] = []
    statuses: list[SourceStatus] = []

    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=20) as client:
        if "njuskalo" in sources:
            result = await scrape_njuskalo(client)
            listings.extend(result.listings)
            statuses.append(result.status)
        if "index_oglasi" in sources:
            result = await scrape_index_oglasi(client)
            listings.extend(result.listings)
            statuses.append(result.status)

    return listings, statuses


async def scrape_njuskalo(client: httpx.AsyncClient) -> ScrapeResult:
    base = "https://www.njuskalo.hr/auti/"
    all_listings: list[Listing] = []
    blocked = False
    errors: list[str] = []

    for model in EV_MODEL_PATHS:
        url = urljoin(base, model)
        try:
            response = await client.get(url)
            text = response.text
        except httpx.HTTPError as exc:
            errors.append(f"{model}: {exc.__class__.__name__}")
            continue

        if _looks_blocked(text):
            blocked = True
            break
        if response.status_code >= 400:
            errors.append(f"{model}: HTTP {response.status_code}")
            continue

        all_listings.extend(_parse_njuskalo_html(text, url))

    if blocked:
        return ScrapeResult(
            listings=[],
            status=SourceStatus(
                source="njuskalo",
                ok=False,
                message="Njuškalo returned a CAPTCHA/challenge page. The app will not bypass it.",
                fetched=0,
            ),
        )

    message = "Fetched Njuškalo model pages."
    if errors:
        message += " Some pages failed: " + "; ".join(errors[:3])

    return ScrapeResult(
        listings=all_listings,
        status=SourceStatus(
            source="njuskalo",
            ok=bool(all_listings),
            message=message if all_listings else "No parseable Njuškalo listings found.",
            fetched=len(all_listings),
        ),
    )


async def scrape_index_oglasi(client: httpx.AsyncClient) -> ScrapeResult:
    params = {
        "module": "vehicles",
        "category": "car",
        "itemPerPage": 24,
        "page": 1,
    }
    url = f"https://www.index.hr/oglasi/api/aditem/widget-search?{urlencode(params)}"

    try:
        response = await client.get(url, headers={**HEADERS, "Accept": "application/json"})
    except httpx.HTTPError as exc:
        return ScrapeResult(
            listings=[],
            status=SourceStatus(
                source="index_oglasi",
                ok=False,
                message=f"Index Oglasi request failed: {exc.__class__.__name__}.",
            ),
        )

    content_type = response.headers.get("content-type", "")
    if response.status_code >= 400 or "application/json" not in content_type:
        return ScrapeResult(
            listings=[],
            status=SourceStatus(
                source="index_oglasi",
                ok=False,
                message=f"Index Oglasi did not return JSON (HTTP {response.status_code}). Endpoint may be blocked or changed.",
                fetched=0,
            ),
        )

    data = response.json()
    rows = data.get("data", []) if isinstance(data, dict) else []
    listings = [_parse_index_item(item) for item in rows]
    listings = [item for item in listings if item is not None]

    return ScrapeResult(
        listings=listings,
        status=SourceStatus(
            source="index_oglasi",
            ok=bool(listings),
            message="Fetched Index Oglasi API results." if listings else "No parseable Index Oglasi listings found.",
            fetched=len(listings),
        ),
    )


def _parse_njuskalo_html(html: str, page_url: str) -> list[Listing]:
    soup = BeautifulSoup(html, "html.parser")
    listings: list[Listing] = []
    seen_urls: set[str] = set()

    for anchor in soup.select('a[href*="/auti/"]'):
        href = anchor.get("href") or ""
        if not href or href in seen_urls:
            continue
        title = _clean_text(anchor.get_text(" ", strip=True))
        if len(title) < 8:
            continue

        parent_text = _clean_text(_nearest_listing_text(anchor))
        combined = _clean_text(f"{title} {parent_text}")
        if not _looks_like_ev(combined):
            continue

        price = _parse_price(combined)
        mileage = _parse_mileage(combined)
        if price is None or mileage is None:
            continue

        full_url = urljoin(page_url, href)
        seen_urls.add(href)
        listings.append(
            Listing(
                id=_listing_id("njuskalo", full_url),
                source="njuskalo",
                title=title,
                url=full_url,
                price_eur=price,
                mileage_km=mileage,
                year=_parse_year(combined),
                location=_parse_location(combined),
                raw_text=combined[:1000],
            )
        )

    return listings


def _parse_index_item(item: dict) -> Listing | None:
    text = _clean_text(" ".join(str(value) for value in item.values() if value is not None))
    if not _looks_like_ev(text):
        return None

    title = item.get("title") or item.get("name") or item.get("summary") or "Index Oglasi listing"
    price = item.get("price") or item.get("priceEur") or _parse_price(text)
    mileage = item.get("mileage") or item.get("mileageKm") or _parse_mileage(text)
    if isinstance(price, str):
        price = _parse_int(price)
    if isinstance(mileage, str):
        mileage = _parse_int(mileage)

    code = item.get("code") or item.get("id") or hashlib.sha1(text.encode()).hexdigest()[:12]
    smart_link = item.get("smartLink") or item.get("url") or ""
    url = smart_link if str(smart_link).startswith("http") else f"https://www.index.hr/oglasi/{smart_link}".rstrip("/")

    return Listing(
        id=_listing_id("index_oglasi", str(code)),
        source="index_oglasi",
        title=str(title),
        url=url,
        price_eur=price if isinstance(price, int) else None,
        mileage_km=mileage if isinstance(mileage, int) else None,
        year=item.get("makeYear") or _parse_year(text),
        location=item.get("locationName") or item.get("location"),
        raw_text=text[:1000],
    )


def _nearest_listing_text(anchor) -> str:
    node = anchor
    for _ in range(5):
        node = node.parent
        if node is None:
            return ""
        text = node.get_text(" ", strip=True)
        if "€" in text or "EUR" in text or "km" in text:
            return text
    return anchor.get_text(" ", strip=True)


def _looks_blocked(html: str) -> bool:
    lowered = html.lower()
    return any(
        marker in lowered
        for marker in ("shieldsquare captcha", "h-captcha", "solve the captcha", "captcha page")
    )


def _looks_like_ev(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in EV_KEYWORDS)


def _parse_price(text: str) -> int | None:
    match = re.search(r"(\d[\d.\s]{2,})\s*(?:€|eur)", text, re.IGNORECASE)
    return _parse_int(match.group(1)) if match else None


def _parse_mileage(text: str) -> int | None:
    match = re.search(r"(\d[\d.\s]{1,})\s*km\b", text, re.IGNORECASE)
    return _parse_int(match.group(1)) if match else None


def _parse_year(text: str) -> int | None:
    match = re.search(r"(?:godište automobila:\s*)?((?:19|20)\d{2})", text, re.IGNORECASE)
    if not match:
        return None
    year = int(match.group(1))
    return year if 1990 <= year <= 2030 else None


def _parse_location(text: str) -> str | None:
    match = re.search(r"Lokacija vozila:\s*([^\.]+)", text, re.IGNORECASE)
    return _clean_text(match.group(1)) if match else None


def _parse_int(value: str) -> int | None:
    digits = re.sub(r"\D", "", value)
    return int(digits) if digits else None


def _clean_text(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())


def _listing_id(source: str, unique: str) -> str:
    digest = hashlib.sha1(unique.encode("utf-8")).hexdigest()[:16]
    return f"{source}-{digest}"
