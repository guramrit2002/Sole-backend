"""
Shared metadata extraction logic.

Given an HTML string, extracts name / price / image using:
  1. JSON-LD Product schema
  2. OpenGraph meta tags
  3. Standard meta / itemprop tags
  4. Heuristic DOM scan (last resort)

Used by all three layers so extraction logic lives in one place.
"""

from __future__ import annotations

import json
import re
from typing import Optional

from bs4 import BeautifulSoup

# Maps currency symbols → ISO 4217 codes
_SYM = {"$": "USD", "€": "EUR", "£": "GBP", "₹": "INR", "¥": "JPY", "₩": "KRW"}
_PRICE_RE = re.compile(
    r"(?P<sym>[$€£₹¥₩])?\s*(?P<amount>\d{1,6}(?:[.,]\d{2,3})*)"
    r"\s*(?P<code>USD|EUR|GBP|INR|JPY|KRW|CAD|AUD|SGD)?",
    re.I,
)


# ── result container ──────────────────────────────────────────────────────────

class ProductData:
    __slots__ = ("name", "price", "currency", "image", "source_layer")

    def __init__(
        self,
        name: Optional[str] = None,
        price: Optional[str] = None,
        currency: Optional[str] = None,
        image: Optional[str] = None,
        source_layer: str = "",
    ):
        self.name = name
        self.price = price
        self.currency = currency
        self.image = image
        self.source_layer = source_layer

    def is_complete(self) -> bool:
        return bool(self.name and self.price and self.image)

    def filled(self) -> int:
        return sum(1 for v in (self.name, self.price, self.image) if v)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "price": self.price,
            "currency": self.currency,
            "image": self.image,
            "source_layer": self.source_layer,
        }

    def __repr__(self) -> str:
        return (
            f"ProductData(name={self.name!r}, price={self.price!r}, "
            f"currency={self.currency!r}, image={self.image!r}, "
            f"source_layer={self.source_layer!r})"
        )


# ── JSON-LD ───────────────────────────────────────────────────────────────────

def _jsonld_product(soup: BeautifulSoup) -> Optional[dict]:
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
            nodes = data if isinstance(data, list) else [data]
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                candidates = node.get("@graph", [node])
                for item in candidates:
                    t = item.get("@type", "")
                    if "Product" in (t if isinstance(t, list) else [t]):
                        return item
        except (json.JSONDecodeError, AttributeError):
            continue
    return None


def _jsonld_price(offers) -> tuple[Optional[str], Optional[str]]:
    if not offers:
        return None, None
    offer = (offers[0] if isinstance(offers, list) else offers) or {}
    price = str(offer.get("price") or offer.get("lowPrice") or "").strip() or None
    currency = (offer.get("priceCurrency") or "").upper() or None
    return price, currency


def _jsonld_image(val) -> Optional[str]:
    if isinstance(val, str):
        return val
    if isinstance(val, list) and val:
        first = val[0]
        return first.get("url") if isinstance(first, dict) else str(first)
    if isinstance(val, dict):
        return val.get("url") or val.get("contentUrl")
    return None


def _from_jsonld(soup: BeautifulSoup) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """Returns (name, price, currency, image)."""
    node = _jsonld_product(soup)
    if not node:
        return None, None, None, None
    price, currency = _jsonld_price(node.get("offers"))
    return node.get("name"), price, currency, _jsonld_image(node.get("image"))


# ── OpenGraph ─────────────────────────────────────────────────────────────────

def _og(soup: BeautifulSoup, *props) -> Optional[str]:
    for prop in props:
        t = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
        if t and t.get("content"):
            return t["content"].strip()
    return None


def _from_og(soup: BeautifulSoup) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    name = _og(soup, "og:title", "twitter:title")
    image = _og(soup, "og:image", "twitter:image")
    price = _og(soup, "product:price:amount", "og:price:amount")
    currency = _og(soup, "product:price:currency", "og:price:currency")
    return name, price, currency, image


# ── Meta / itemprop ───────────────────────────────────────────────────────────

def _meta(soup: BeautifulSoup, *names) -> Optional[str]:
    for name in names:
        t = (soup.find("meta", attrs={"name": name})
             or soup.find("meta", attrs={"itemprop": name}))
        if t and t.get("content"):
            return t["content"].strip()
    return None


def _from_meta(soup: BeautifulSoup) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    title_tag = soup.title
    page_title = title_tag.string.strip() if (title_tag and title_tag.string) else None
    name = _meta(soup, "title") or page_title
    image = _meta(soup, "image", "thumbnail")
    price = _meta(soup, "price")
    currency = _meta(soup, "currency")
    return name, price, currency, image


# ── DOM heuristic price scan ──────────────────────────────────────────────────

def _parse_price_text(text: str) -> tuple[Optional[str], Optional[str]]:
    """
    Extract (amount, currency_code) from a raw price string.
    Requires at least a currency symbol OR a currency code — bare numbers
    (e.g. shoe sizes like "12" before "$71") are rejected.
    """
    for m in _PRICE_RE.finditer(text):
        sym  = m.group("sym") or ""
        code = m.group("code") or _SYM.get(sym)
        if not code:          # no currency signal — skip (could be a size number)
            continue
        amount = m.group("amount").replace(",", "")
        return amount, code.upper()
    return None, None


def _price_from_dom(soup: BeautifulSoup) -> tuple[Optional[str], Optional[str]]:
    # Pass 1 — targeted selectors (cheapest)
    for sel in [
        "[itemprop='price']", "[data-price]",
        "[class*='price']", "[class*='Price']",
        "[class*='cost']",  "[class*='amount']",
        "[class*='final']",
    ]:
        el = soup.select_one(sel)
        if not el:
            continue
        text = el.get("data-price") or el.get("content") or el.get_text(" ", strip=True)
        amount, code = _parse_price_text(text)
        if amount:
            return amount, code

    # Pass 2 — scan ALL visible text nodes for currency symbols.
    # Catches sites like VegNonVeg that render ₹ + digits in plain <span>s
    # with no semantic class names.
    _SKIP_TAGS = {"script", "style", "noscript", "meta", "head"}
    for string in soup.strings:
        parent = string.parent
        if not parent or parent.name in _SKIP_TAGS:
            continue
        text = " ".join(string.split())   # collapse whitespace
        if not any(sym in text for sym in _SYM):
            continue
        amount, code = _parse_price_text(text)
        if amount:
            return amount, code

    return None, None


# ── master parse ──────────────────────────────────────────────────────────────

def parse(html: str, source_layer: str = "") -> ProductData:
    """
    Run all strategies, merge results (higher priority wins per field),
    return a ProductData object.
    """
    soup = BeautifulSoup(html, "lxml")

    jn, jp, jc, ji = _from_jsonld(soup)
    on, op, oc, oi = _from_og(soup)
    mn, mp, mc, mi = _from_meta(soup)

    def first(*vals):
        return next((v for v in vals if v), None)

    price = first(jp, op, mp)
    currency = first(jc, oc, mc)

    if not price:
        price, fallback_curr = _price_from_dom(soup)
        currency = currency or fallback_curr

    return ProductData(
        name=first(jn, on, mn),
        price=price,
        currency=currency,
        image=first(ji, oi, mi),
        source_layer=source_layer,
    )
