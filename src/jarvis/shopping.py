from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote_plus

from .web_context import WebCandidate


@dataclass(frozen=True)
class ShoppingSite:
    key: str
    title: str
    home_url: str
    search_url: str
    deals_url: str


SHOPPING_SITES: dict[str, ShoppingSite] = {
    "plasico": ShoppingSite(
        key="plasico",
        title="Plasico",
        home_url="https://plasico.bg",
        search_url="https://www.google.com/search?q=site%3Aplasico.bg+{query}",
        deals_url="https://www.google.com/search?q=site%3Aplasico.bg+%D0%BD%D0%B0%D0%BC%D0%B0%D0%BB%D0%B5%D0%BD%D0%B8%D1%8F+{query}",
    ),
    "пласико": ShoppingSite(
        key="plasico",
        title="Plasico",
        home_url="https://plasico.bg",
        search_url="https://www.google.com/search?q=site%3Aplasico.bg+{query}",
        deals_url="https://www.google.com/search?q=site%3Aplasico.bg+%D0%BD%D0%B0%D0%BC%D0%B0%D0%BB%D0%B5%D0%BD%D0%B8%D1%8F+{query}",
    ),
    "ozone": ShoppingSite(
        key="ozone",
        title="Ozone",
        home_url="https://www.ozone.bg",
        search_url="https://www.google.com/search?q=site%3Aozone.bg+{query}",
        deals_url="https://www.google.com/search?q=site%3Aozone.bg+%D0%BD%D0%B0%D0%BC%D0%B0%D0%BB%D0%B5%D0%BD%D0%B8%D1%8F+{query}",
    ),
    "озон": ShoppingSite(
        key="ozone",
        title="Ozone",
        home_url="https://www.ozone.bg",
        search_url="https://www.google.com/search?q=site%3Aozone.bg+{query}",
        deals_url="https://www.google.com/search?q=site%3Aozone.bg+%D0%BD%D0%B0%D0%BC%D0%B0%D0%BB%D0%B5%D0%BD%D0%B8%D1%8F+{query}",
    ),
}

SHOPPING_SITES["emag"] = ShoppingSite(
    key="emag",
    title="eMAG",
    home_url="https://www.emag.bg",
    search_url="https://www.google.com/search?q=site%3Aemag.bg+{query}",
    deals_url="https://www.google.com/search?q=site%3Aemag.bg+%D0%BD%D0%B0%D0%BC%D0%B0%D0%BB%D0%B5%D0%BD%D0%B8%D1%8F+{query}",
)
SHOPPING_SITES["емаг"] = SHOPPING_SITES["emag"]
SHOPPING_SITES["technopolis"] = ShoppingSite(
    key="technopolis",
    title="Technopolis",
    home_url="https://www.technopolis.bg",
    search_url="https://www.google.com/search?q=site%3Atechnopolis.bg+{query}",
    deals_url="https://www.google.com/search?q=site%3Atechnopolis.bg+%D0%BD%D0%B0%D0%BC%D0%B0%D0%BB%D0%B5%D0%BD%D0%B8%D1%8F+{query}",
)
SHOPPING_SITES["технополис"] = SHOPPING_SITES["technopolis"]
SHOPPING_SITES["technomarket"] = ShoppingSite(
    key="technomarket",
    title="Technomarket",
    home_url="https://www.technomarket.bg",
    search_url="https://www.google.com/search?q=site%3Atechnomarket.bg+{query}",
    deals_url="https://www.google.com/search?q=site%3Atechnomarket.bg+%D0%BD%D0%B0%D0%BC%D0%B0%D0%BB%D0%B5%D0%BD%D0%B8%D1%8F+{query}",
)
SHOPPING_SITES["техномаркет"] = SHOPPING_SITES["technomarket"]
SHOPPING_SITES["ardes"] = ShoppingSite(
    key="ardes",
    title="Ardes",
    home_url="https://ardes.bg",
    search_url="https://www.google.com/search?q=site%3Aardes.bg+{query}",
    deals_url="https://www.google.com/search?q=site%3Aardes.bg+%D0%BD%D0%B0%D0%BC%D0%B0%D0%BB%D0%B5%D0%BD%D0%B8%D1%8F+{query}",
)
SHOPPING_SITES["ардес"] = SHOPPING_SITES["ardes"]


def find_site(name: str) -> ShoppingSite | None:
    return SHOPPING_SITES.get(name.strip().lower())


def site_search_candidate(site: ShoppingSite, query: str) -> WebCandidate:
    encoded = quote_plus(query)
    return WebCandidate(title=f"{site.title}: {query}", url=site.search_url.format(query=encoded))


def deal_candidates(query: str = "") -> list[WebCandidate]:
    seen: set[str] = set()
    candidates: list[WebCandidate] = []
    encoded = quote_plus(query)
    for site in SHOPPING_SITES.values():
        if site.key in seen:
            continue
        seen.add(site.key)
        title = f"{site.title} deals" if not query else f"{site.title} deals: {query}"
        candidates.append(WebCandidate(title=title, url=site.deals_url.format(query=encoded)))
    return candidates
