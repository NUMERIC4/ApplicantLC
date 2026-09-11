from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from backend.database import get_db
from backend.models import Candidate
from backend.schemas import CandidateRead, CandidateBase

router = APIRouter(prefix="/api/candidates", tags=["Candidates"])

@router.get("/current", response_model=CandidateRead)
async def get_current_candidate(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Candidate).limit(1))
    cand = result.scalars().first()
    if not cand:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return cand

@router.put("/current", response_model=CandidateRead)
async def update_current_candidate(payload: CandidateBase, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Candidate).limit(1))
    cand = result.scalars().first()
    if not cand:
        cand = Candidate(**payload.model_dump())
        db.add(cand)
    else:
        for k, v in payload.model_dump().items():
            setattr(cand, k, v)

    await db.commit()
    await db.refresh(cand)
    return cand
