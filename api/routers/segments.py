from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from api.database import get_db
from api.schemas import SegmentResponse, SegmentSummary


router = APIRouter(prefix="/api/v1/customers", tags=["customers"])


@router.get("/segments", response_model=SegmentResponse)
def get_customer_segments(db: Session = Depends(get_db)):
    try:
        rows = db.execute(
            text("""
                SELECT segment_name, COUNT(*) AS customer_count,
                       AVG(recency) AS average_recency_days,
                       AVG(frequency) AS average_frequency,
                       AVG(monetary) AS average_monetary
                FROM gold.mart_customer_segments
                GROUP BY segment_name
                ORDER BY customer_count DESC
            """)
        ).mappings().all()
    except SQLAlchemyError as error:
        raise HTTPException(status_code=503, detail=f"Segment query failed: {error}") from error

    segments = [SegmentSummary(**row) for row in rows]
    return SegmentResponse(
        total_customers=sum(segment.customer_count for segment in segments),
        segments=segments,
    )
