from fastapi import APIRouter, Depends

from ..config import get_config
from ..deps import get_grocy
from ..grocy.client import GrocyClient, GrocyError
from ..schemas import GrocyMeta, IdName, ProductHit, StoreCreate
from ..services.trips import new_product_defaults, suggest_products

router = APIRouter(prefix="/api/grocy", tags=["grocy"])


def _id_names(rows) -> list[IdName]:
    return sorted(
        (IdName(id=int(r["id"]), name=r["name"]) for r in rows), key=lambda x: x.name.lower()
    )


@router.get("/meta", response_model=GrocyMeta)
async def meta(grocy: GrocyClient = Depends(get_grocy)):
    """Locations, stores and units for the pickers in the review screen."""
    md = await grocy.master_data(get_config().grocy_cache_seconds)
    version = None
    if md.reachable:  # no point asking a Grocy that just failed to answer
        try:
            version = ((await grocy.system_info()).get("grocy_version") or {}).get("Version")
        except GrocyError as exc:
            if exc.status == 401:
                raise
    units = [u for u in md.quantity_units.values() if int(u.get("active", 1) or 0)]
    return GrocyMeta(
        grocy_version=version,
        locations=_id_names(md.locations),
        stores=_id_names(md.stores),
        quantity_units=_id_names(units),
        product_groups=_id_names(md.product_groups),
        new_product_defaults=new_product_defaults(md),
        grocy_reachable=md.reachable,
    )


@router.get("/products", response_model=list[ProductHit])
async def search_products(q: str = "", limit: int = 20, grocy: GrocyClient = Depends(get_grocy)):
    """Product picker search: substring hits first, then fuzzy ones."""
    md = await grocy.master_data(get_config().grocy_cache_seconds)
    limit = max(1, min(limit, 100))
    products = [p for p in md.products.values() if int(p.get("active", 1) or 0)]
    query = q.strip().lower()
    if not query:
        products.sort(key=lambda p: p["name"].lower())
        return [ProductHit(id=int(p["id"]), name=p["name"]) for p in products[:limit]]
    hits = [
        ProductHit(id=int(p["id"]), name=p["name"], score=1.0)
        for p in sorted(
            products, key=lambda p: (not p["name"].lower().startswith(query), p["name"].lower())
        )
        if query in p["name"].lower()
    ][:limit]
    seen = {h.id for h in hits}
    for hit in suggest_products(q, md, limit=limit):
        if hit.id not in seen and len(hits) < limit:
            hits.append(hit)
    return hits


@router.post("/stores", response_model=IdName, status_code=201)
async def create_store(body: StoreCreate, grocy: GrocyClient = Depends(get_grocy)):
    """Adds a store to Grocy (handy the first time a receipt from it shows up)."""
    name = body.name.strip()
    store_id = await grocy.create_object("shopping_locations", {"name": name})
    return IdName(id=store_id, name=name)
