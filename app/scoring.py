from __future__ import annotations

from statistics import median

from .models import Listing, SearchFilters


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _round_to_50(value: float) -> int:
    return int(round(value / 50) * 50)


def filter_and_rank(listings: list[Listing], filters: SearchFilters) -> list[Listing]:
    candidates: list[Listing] = []
    seen: set[str] = set()

    for item in listings:
        if item.id in seen:
            continue
        seen.add(item.id)

        if item.price_eur is None or item.mileage_km is None:
            continue
        if item.price_eur < filters.min_price or item.price_eur > filters.max_price:
            continue
        if filters.max_mileage is not None and item.mileage_km > filters.max_mileage:
            continue
        candidates.append(item)

    if not candidates:
        return []

    value_indexes = [
        _value_index(item.price_eur or 0, item.mileage_km or 0)
        for item in candidates
    ]
    min_index = min(value_indexes)
    max_index = max(value_indexes)
    median_price = median([item.price_eur or 0 for item in candidates])
    median_mileage = median([item.mileage_km or 0 for item in candidates])

    for item in candidates:
        item.value_index = _value_index(item.price_eur or 0, item.mileage_km or 0)
        value_score = _score(item.value_index, min_index, max_index)
        market_score = _market_discount_score(item)
        item.score = round((value_score * 0.6) + (market_score * 0.4), 1)
        item.negotiation_open_eur = _negotiation_open(item)
        item.negotiation_ceiling_eur = _negotiation_ceiling(item, median_price, median_mileage)
        item.reasons = _reasons(item, median_price, median_mileage)

    candidates.sort(key=lambda item: (-(item.score or 0), item.price_eur or 10**9))
    for index, item in enumerate(candidates, start=1):
        item.rank = index
    return candidates


def _value_index(price: int, mileage: int) -> float:
    # Treat 10,000 km as roughly 350 EUR of extra wear for ranking purposes.
    return price + (mileage * 0.035)


def _score(value_index: float, min_index: float, max_index: float) -> float:
    if max_index == min_index:
        return 100.0
    normalized = 1 - ((value_index - min_index) / (max_index - min_index))
    return round(_clamp(normalized * 100, 0, 100), 1)


def _market_discount_score(item: Listing) -> float:
    if item.price_eur is None or not item.market_median_price_eur:
        return 50.0
    delta_pct = ((item.price_eur - item.market_median_price_eur) / item.market_median_price_eur) * 100
    # Equal to market is neutral. Roughly 25% under market reaches 100, 25% over market reaches 0.
    return round(_clamp(50 - (delta_pct * 2), 0, 100), 1)


def _negotiation_open(item: Listing) -> int:
    price = item.price_eur or 0
    mileage = item.mileage_km or 0
    if item.market_median_price_eur and item.market_median_price_eur < price:
        market_pressure = (price - item.market_median_price_eur) * 0.45
    else:
        market_pressure = 0
    mileage_pressure = _clamp(mileage / 300000, 0.02, 0.14)
    discount = price * (0.055 + mileage_pressure) + market_pressure
    return max(0, _round_to_50(price - _clamp(discount, 350, 1800)))


def _negotiation_ceiling(item: Listing, median_price: float, median_mileage: float) -> int:
    price = item.price_eur or 0
    mileage = item.mileage_km or 0
    if mileage <= median_mileage and price <= median_price:
        ceiling = price * 0.97
    elif mileage > median_mileage and price > median_price:
        ceiling = price * 0.9
    else:
        ceiling = price * 0.94
    if item.market_median_price_eur and item.market_median_price_eur < ceiling:
        ceiling = min(ceiling, item.market_median_price_eur * 0.98)
    return max(0, _round_to_50(ceiling))


def _reasons(item: Listing, median_price: float, median_mileage: float) -> list[str]:
    price = item.price_eur or 0
    mileage = item.mileage_km or 0
    reasons = []

    if price <= median_price:
        reasons.append("Price is at or below your shortlist median.")
    else:
        reasons.append("Price is above your shortlist median.")

    if mileage <= median_mileage:
        reasons.append("Mileage is at or below your shortlist median.")
    else:
        reasons.append("Mileage is above your shortlist median.")

    if item.market_delta_eur is not None:
        if item.market_delta_eur < 0:
            reasons.append(f"{abs(item.market_delta_eur):,} EUR under AutoScout24 median.")
        elif item.market_delta_eur > 0:
            reasons.append(f"{item.market_delta_eur:,} EUR over AutoScout24 median.")
        else:
            reasons.append("Matches the AutoScout24 median.")
    elif item.market_status not in ("not_checked", "needs_refresh"):
        reasons.append(f"Market check: {item.market_status.replace('_', ' ')}.")

    if mileage > 150000:
        reasons.append("High mileage: inspect battery health and service history closely.")
    if item.year and item.year < 2016:
        reasons.append("Older EV: check battery degradation, charger type, and range.")
    return reasons
