from catalog.store import CatalogStore


def get_catalog(db_path: str) -> dict:
    store = CatalogStore(db_path)
    entries = store.catalog()
    products = store.list_products()
    return {
        "products": [{"id": p.id, "name": p.name, "status": p.status} for p in products],
        "catalog": [
            {"product": e.product, "aliases": e.aliases} for e in entries
        ],
    }
