from __future__ import annotations

import json
import unittest

from app.market import (
    apply_market_stats,
    build_autoscout24_url,
    compute_market_stats,
    parse_autoscout24_html,
    MarketListing,
    MarketStats,
)
from app.models import Listing, SearchFilters
from app.scoring import filter_and_rank


class AutoScout24UrlTests(unittest.TestCase):
    def test_builds_exact_year_ev_urls(self) -> None:
        cases = [
            ("Renault", "Zoe", 2017, "/lst/renault/zoe/ft_electric"),
            ("Smart", "Fortwo", 2019, "/lst/smart/fortwo/ft_electric"),
            ("Renault", "Twingo", 2020, "/lst/renault/twingo/ft_electric"),
        ]

        for make, model, year, path in cases:
            with self.subTest(make=make, model=model):
                url = build_autoscout24_url(make, model, year)
                self.assertIn(path, url)
                self.assertIn(f"fregfrom={year}", url)
                self.assertIn(f"fregto={year}", url)
                self.assertIn("ustate=N%2CU", url)


class AutoScout24ParserTests(unittest.TestCase):
    def test_parses_next_data_listings(self) -> None:
        payload = {
            "props": {
                "pageProps": {
                    "listings": [
                        {
                            "price": {"priceFormatted": "€ 8,950.-"},
                            "url": "/offers/renault-zoe-electric-blue-123",
                            "location": {"city": "Berlin", "country": "Germany"},
                            "images": [{"src": "https://img.example/zoe.jpg"}],
                            "vehicleDetails": [
                                {"ariaLabel": "Mileage", "text": "42,000 km"},
                                {"ariaLabel": "First registration", "text": "05/2017"},
                                {"ariaLabel": "Fuel type", "text": "Electric"},
                            ],
                        }
                    ]
                }
            }
        }
        html = f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script></html>'

        listings = parse_autoscout24_html(html)

        self.assertEqual(len(listings), 1)
        self.assertEqual(listings[0].price_eur, 8950)
        self.assertEqual(listings[0].mileage_km, 42000)
        self.assertEqual(listings[0].first_registration_year, 2017)
        self.assertEqual(listings[0].location, "Berlin, Germany")
        self.assertEqual(listings[0].url, "https://www.autoscout24.com/offers/renault-zoe-electric-blue-123")
        self.assertEqual(listings[0].image_url, "https://img.example/zoe.jpg")


class MarketStatsTests(unittest.TestCase):
    def test_computes_stats_and_local_delta(self) -> None:
        stats = compute_market_stats(
            [
                MarketListing(8000, 50000, 2019, None, None, None),
                MarketListing(10000, 40000, 2019, None, None, None),
                MarketListing(14000, 30000, 2019, None, None, None),
            ],
            "https://example.test/search",
        )
        listing = Listing(
            id="manual-test",
            source="manual",
            title="Smart Fortwo",
            make="Smart",
            model="Fortwo",
            url="https://seller.test",
            price_eur=9000,
            mileage_km=42000,
            year=2019,
        )

        apply_market_stats(listing, stats)

        self.assertEqual(stats.average_price_eur, 10667)
        self.assertEqual(stats.median_price_eur, 10000)
        self.assertEqual(stats.sample_size, 3)
        self.assertEqual(stats.min_price_eur, 8000)
        self.assertEqual(stats.max_price_eur, 14000)
        self.assertEqual(listing.market_delta_eur, -1000)
        self.assertEqual(listing.market_delta_pct, -10.0)


class RankingTests(unittest.TestCase):
    def test_market_median_moves_below_market_up(self) -> None:
        filters = SearchFilters(min_price=0, max_price=20000, sources=["manual"])
        listings = []
        for label, price in [("below", 8000), ("equal", 10000), ("above", 12000)]:
            listing = Listing(
                id=f"manual-{label}",
                source="manual",
                title=f"Renault Zoe {label}",
                make="Renault",
                model="Zoe",
                url=f"https://seller.test/{label}",
                price_eur=price,
                mileage_km=50000,
                year=2017,
            )
            apply_market_stats(
                listing,
                MarketStats(
                    average_price_eur=10000,
                    median_price_eur=10000,
                    sample_size=12,
                    min_price_eur=8000,
                    max_price_eur=13000,
                    source_url="https://example.test/search",
                    status="ok",
                ),
            )
            listings.append(listing)

        ranked = filter_and_rank(listings, filters)

        self.assertEqual([item.id for item in ranked], ["manual-below", "manual-equal", "manual-above"])
        self.assertGreater(ranked[0].score or 0, ranked[1].score or 0)
        self.assertGreater(ranked[1].score or 0, ranked[2].score or 0)


if __name__ == "__main__":
    unittest.main()
