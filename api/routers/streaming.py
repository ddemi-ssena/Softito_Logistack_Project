from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from api.database import get_db
from api.schemas import StreamingStatsResponse


router = APIRouter(prefix="/api/v1/streaming", tags=["streaming"])


@router.get("/stats", response_model=StreamingStatsResponse)
def get_streaming_stats(db: Session = Depends(get_db)):
    try:
        result = db.execute(
            text("""
                SELECT COUNT(*) AS total_events, MAX(consumed_at) AS last_event_at
                FROM streaming.order_events
            """)
        ).mappings().one()
    except SQLAlchemyError as error:
        raise HTTPException(status_code=503, detail=f"Streaming query failed: {error}") from error
    return StreamingStatsResponse(**result)
