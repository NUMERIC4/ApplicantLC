from datetime import date
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from backend.database import get_db
from backend.models import DailyBatch, Application
from backend.schemas import DailyBatchCreate, DailyBatchRead, DailyBatchUpdate

router = APIRouter(prefix="/api/daily-batches", tags=["Daily Batches"])

@router.get("", response_model=List[DailyBatchRead])
async def list_daily_batches(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DailyBatch).order_by(DailyBatch.day_no.desc()))
    return result.scalars().all()

@router.get("/today", response_model=DailyBatchRead)
async def get_or_create_today_batch(db: AsyncSession = Depends(get_db)):
    today = date.today()
    result = await db.execute(select(DailyBatch).where(DailyBatch.batch_date == today))
    batch = result.scalars().first()
    if not batch:
        # compute next day_no
        latest_res = await db.execute(select(DailyBatch).order_by(DailyBatch.day_no.desc()).limit(1))
        latest = latest_res.scalars().first()
        next_day = (latest.day_no + 1) if latest else 1

        batch = DailyBatch(
            batch_date=today,
            day_no=next_day,
            target_evaluation=5,
            target_application=3,
            actual_evaluation=0,
            actual_application=0,
            focus="New Daily Focus Pool",
            status="in progress",
            notes="Daily sprint started"
        )
        db.add(batch)
        await db.commit()
        await db.refresh(batch)
    return batch

@router.post("", response_model=DailyBatchRead)
async def create_daily_batch(payload: DailyBatchCreate, db: AsyncSession = Depends(get_db)):
    batch = DailyBatch(**payload.model_dump())
    db.add(batch)
    await db.commit()
    await db.refresh(batch)
    return batch

@router.put("/{batch_id}", response_model=DailyBatchRead)
async def update_daily_batch(batch_id: int, payload: DailyBatchUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DailyBatch).where(DailyBatch.id == batch_id))
    batch = result.scalars().first()
    if not batch:
        raise HTTPException(status_code=404, detail="Daily Batch not found")

    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(batch, key, value)

    await db.commit()
    await db.refresh(batch)
    return batch

@router.post("/{batch_id}/increment-evaluation", response_model=DailyBatchRead)
async def increment_batch_evaluation(batch_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DailyBatch).where(DailyBatch.id == batch_id))
    batch = result.scalars().first()
    if not batch:
        raise HTTPException(status_code=404, detail="Daily Batch not found")

    batch.actual_evaluation += 1
    await db.commit()
    await db.refresh(batch)
    return batch
