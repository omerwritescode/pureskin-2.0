"""The product catalog (roadmap step 7c-iii): backend/catalog/products.json, loaded and checked.

    load_catalog(path) -> Catalog        every row cleaned, normalised and checked (or CatalogError)
    product_records(catalog)             the rows as routine-engine product records
    CATALOG_CONFIG_VERSION

See backend/catalog/README.md (the rows, the checks, how to add a row).
"""

from .catalog_config import CATALOG_CONFIG_VERSION
from .loader import CATALOG_FILE, Catalog, CatalogError, CatalogProduct, check_rows, load_catalog, product_records

__all__ = [
    "CATALOG_CONFIG_VERSION",
    "CATALOG_FILE",
    "Catalog",
    "CatalogError",
    "CatalogProduct",
    "check_rows",
    "load_catalog",
    "product_records",
]
