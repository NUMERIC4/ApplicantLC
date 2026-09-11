from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from backend.database import get_db
from backend.models import SearchAlert
from backend.schemas import SearchAlertCreate, SearchAlertRead

router = APIRouter(prefix="/api/search-alerts", tags=["Search Alerts"])

@router.get("", response_model=List[SearchAlertRead])
async def list_search_alerts(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SearchAlert).order_by(SearchAlert.created_date.desc()))
    return result.scalars().all()

@router.post("", response_model=SearchAlertRead)
async def create_search_alert(payload: SearchAlertCreate, db: AsyncSession = Depends(get_db)):
    alert = SearchAlert(**payload.model_dump())
    db.add(alert)
    await db.commit()
    await db.refresh(alert)
    return alert

@router.put("/{alert_id}", response_model=SearchAlertRead)
async def update_search_alert(alert_id: int, payload: dict, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SearchAlert).where(SearchAlert.id == alert_id))
    alert = result.scalars().first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    for k, v in payload.items():
        if hasattr(alert, k):
            setattr(alert, k, v)

    await db.commit()
    await db.refresh(alert)
    return alert

@router.delete("/{alert_id}")
async def delete_search_alert(alert_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SearchAlert).where(SearchAlert.id == alert_id))
    alert = result.scalars().first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    await db.delete(alert)
    await db.commit()
    return {"message": "Alert deleted"}
