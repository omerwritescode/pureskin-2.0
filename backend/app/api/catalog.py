from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models import Product

router = APIRouter(
    prefix="/api/catalog", tags=["catalog"], dependencies=[Depends(get_current_user)]
)


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    brand: str
    category: str | None
    description: str | None
    ingredients: list[str]
    image_url: str | None


class ProductPage(BaseModel):
    items: list[ProductOut]
    total: int
    page: int
    page_size: int


@router.get("", response_model=ProductPage)
def list_products(
    search: str | None = Query(None, max_length=100),
    category: str | None = Query(None, max_length=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> ProductPage:
    stmt = select(Product)
    if search and search.strip():
        term = search.strip()
        stmt = stmt.where(
            or_(
                Product.name.icontains(term, autoescape=True),
                Product.brand.icontains(term, autoescape=True),
            )
        )
    if category:
        stmt = stmt.where(Product.category == category)

    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    items = db.scalars(
        stmt.order_by(Product.name, Product.id).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return ProductPage(items=items, total=total, page=page, page_size=page_size)


# Declared before /{product_id} so "categories" isn't parsed as an id.
@router.get("/categories", response_model=list[str])
def list_categories(db: Session = Depends(get_db)) -> list[str]:
    """Distinct product categories, for the catalog's filter dropdown."""
    return db.scalars(
        select(Product.category).where(Product.category.is_not(None)).distinct().order_by(Product.category)
    ).all()


@router.get("/{product_id}", response_model=ProductOut)
def get_product(product_id: int, db: Session = Depends(get_db)) -> Product:
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return product
