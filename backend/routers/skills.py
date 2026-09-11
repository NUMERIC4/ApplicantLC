from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from backend.database import get_db
from backend.models import Skill
from backend.schemas import SkillCreate, SkillRead

router = APIRouter(prefix="/api/skills", tags=["Skills & Learning Curve"])

@router.get("", response_model=List[SkillRead])
async def list_skills(category: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    query = select(Skill)
    if category:
        query = query.where(Skill.category == category)
    query = query.order_by(Skill.category.asc(), Skill.name.asc())
    result = await db.execute(query)
    return result.scalars().all()

@router.post("", response_model=SkillRead)
async def create_skill(payload: SkillCreate, db: AsyncSession = Depends(get_db)):
    skill = Skill(**payload.model_dump())
    db.add(skill)
    await db.commit()
    await db.refresh(skill)
    return skill

@router.put("/{skill_id}", response_model=SkillRead)
async def update_skill(skill_id: int, payload: dict, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Skill).where(Skill.id == skill_id))
    skill = result.scalars().first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    for k, v in payload.items():
        if hasattr(skill, k):
            setattr(skill, k, v)

    await db.commit()
    await db.refresh(skill)
    return skill

@router.delete("/{skill_id}")
async def delete_skill(skill_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Skill).where(Skill.id == skill_id))
    skill = result.scalars().first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    await db.delete(skill)
    await db.commit()
    return {"message": "Skill deleted"}
