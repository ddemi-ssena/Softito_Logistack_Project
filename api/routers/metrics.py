from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from api.database import get_db
from api.schemas import KPIResponse


router = APIRouter(prefix="/api/v1/metrics", tags=["metrics"])


@router.get("/kpis", response_model=KPIResponse)
def get_kpis(db: Session = Depends(get_db)):
    try:
        result = db.execute(
            text("""
                WITH item_totals AS (
                    SELECT order_id, SUM(price) AS total_revenue
                    FROM gold.fact_order_items
                    GROUP BY order_id
                )
                SELECT COALESCE(SUM(COALESCE(i.total_revenue, o.total_product_amount)), 0)
                           AS total_revenue,
                       COUNT(*) AS total_orders,
                       SUM(COALESCE(i.total_revenue, o.total_product_amount))
                           / NULLIF(COUNT(*), 0) AS average_order_value,
                       AVG(o.delivery_days) FILTER (
                           WHERE o.order_status = 'delivered' AND o.delivery_days IS NOT NULL
                       ) AS average_delivery_days
                FROM gold.fact_orders AS o
                LEFT JOIN item_totals AS i ON i.order_id = o.order_id
                WHERE o.order_status IN ('approved', 'delivered')
            """)
        ).mappings().one()
    except SQLAlchemyError as error:
        raise HTTPException(status_code=503, detail=f"KPI query failed: {error}") from error
    return KPIResponse(**result)
