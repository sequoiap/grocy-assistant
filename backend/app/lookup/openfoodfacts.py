"""Barcode -> product name lookup against the Open*Facts family of open databases."""

from __future__ import annotations

import logging

import httpx

log = logging.getLogger(__name__)

# Food first; the sibling databases cover household, beauty and pet products.
_HOSTS = (
    ("openfoodfacts", "https://world.openfoodfacts.org"),
    ("openproductsfacts", "https://world.openproductsfacts.org"),
    ("openbeautyfacts", "https://world.openbeautyfacts.org"),
    ("openpetfoodfacts", "https://world.openpetfoodfacts.org"),
)
_FIELDS = "product_name,product_name_en,generic_name,brands,quantity,image_front_small_url"
_HEADERS = {"User-Agent": "grocy-assistant/0.1 (self-hosted barcode lookup)"}


def _clean(value: object) -> str:
    return " ".join(str(value or "").split())


def suggested_name(name: str, brand: str, quantity: str) -> str:
    """'Brand Product Name (12 oz)' without repeating a brand already in the name."""
    parts = []
    if brand and brand.lower() not in name.lower():
        parts.append(brand)
    parts.append(name)
    out = " ".join(p for p in parts if p)
    if quantity and quantity.lower() not in out.lower():
        out = f"{out} ({quantity})" if out else quantity
    return out.strip()


async def lookup_barcode(http: httpx.AsyncClient, barcode: str) -> dict:
    """Returns ``{"found": bool, "name", "brand", "quantity", "image_url", "source",
    "suggested_name"}``. Never raises: a lookup failure is just "not found"."""
    result = {
        "found": False,
        "name": "",
        "brand": "",
        "quantity": "",
        "image_url": None,
        "source": None,
        "suggested_name": "",
    }
    if not barcode.isdigit() or not 8 <= len(barcode) <= 14:
        return result
    for source, host in _HOSTS:
        try:
            resp = await http.get(
                f"{host}/api/v2/product/{barcode}.json",
                params={"fields": _FIELDS},
                headers=_HEADERS,
                timeout=6.0,
            )
            if resp.status_code != 200:
                continue
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            log.info("barcode lookup via %s failed: %s", source, exc)
            continue
        product = data.get("product") or {}
        name = _clean(
            product.get("product_name_en")
            or product.get("product_name")
            or product.get("generic_name")
        )
        if data.get("status") != 1 or not name:
            continue
        brand = _clean((product.get("brands") or "").split(",")[0])
        quantity = _clean(product.get("quantity"))
        result.update(
            found=True,
            name=name,
            brand=brand,
            quantity=quantity,
            image_url=product.get("image_front_small_url") or None,
            source=source,
            suggested_name=suggested_name(name, brand, quantity),
        )
        return result
    return result
