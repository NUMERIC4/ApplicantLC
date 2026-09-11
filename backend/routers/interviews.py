from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from backend.database import get_db
from backend.models import Interview, Application
from backend.schemas import InterviewCreate, InterviewRead

router = APIRouter(prefix="/api/interviews", tags=["Interviews"])

@router.get("", response_model=List[InterviewRead])
async def list_interviews(application_id: Optional[int] = None, db: AsyncSession = Depends(get_db)):
    query = select(Interview)
    if application_id:
        query = query.where(Interview.application_id == application_id)
    query = query.order_by(Interview.interview_date.asc())
    result = await db.execute(query)
    return result.scalars().all()

@router.post("", response_model=InterviewRead)
async def create_interview(payload: InterviewCreate, db: AsyncSession = Depends(get_db)):
    iv = Interview(**payload.model_dump())
    db.add(iv)

    # Update parent application status
    app_res = await db.execute(select(Application).where(Application.id == payload.application_id))
    app = app_res.scalars().first()
    if app:
        app.status = "Interview"
        app.current_stage = "Interview"

    await db.commit()
    await db.refresh(iv)
    return iv

@router.put("/{interview_id}", response_model=InterviewRead)
async def update_interview(interview_id: int, payload: dict, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Interview).where(Interview.id == interview_id))
    iv = result.scalars().first()
    if not iv:
        raise HTTPException(status_code=404, detail="Interview not found")

    for k, v in payload.items():
        if hasattr(iv, k):
            setattr(iv, k, v)

    await db.commit()
    await db.refresh(iv)
    return iv

@router.delete("/{interview_id}")
async def delete_interview(interview_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Interview).where(Interview.id == interview_id))
    iv = result.scalars().first()
    if not iv:
        raise HTTPException(status_code=404, detail="Interview not found")
    await db.delete(iv)
    await db.commit()
    return {"message": "Interview deleted"}
