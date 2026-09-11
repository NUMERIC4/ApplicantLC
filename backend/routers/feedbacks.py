from datetime import date
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from backend.database import get_db
from backend.models import Feedback, Application, Skill, Company
from backend.schemas import FeedbackCreate, FeedbackRead

router = APIRouter(prefix="/api/feedbacks", tags=["Feedbacks"])

@router.get("", response_model=List[FeedbackRead])
async def list_feedbacks(application_id: Optional[int] = None, db: AsyncSession = Depends(get_db)):
    query = select(Feedback)
    if application_id:
        query = query.where(Feedback.application_id == application_id)
    query = query.order_by(Feedback.feedback_date.desc(), Feedback.id.desc())
    result = await db.execute(query)
    return result.scalars().all()

@router.post("", response_model=FeedbackRead)
async def create_feedback(payload: FeedbackCreate, db: AsyncSession = Depends(get_db)):
    # Verify application
    app_res = await db.execute(select(Application).where(Application.id == payload.application_id))
    app = app_res.scalars().first()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    fb_data = payload.model_dump(exclude={"add_to_learning_curve"})
    if not fb_data.get("company_id"):
        fb_data["company_id"] = app.company_id

    feedback = Feedback(**fb_data)
    db.add(feedback)

    # Update application feedback status
    app.feedback_status = "received"
    if app.status != "offer":
        app.status = "Rejected"

    # Add to candidate learning curve / skills if requested and skill_gap exists
    if payload.add_to_learning_curve and payload.skill_gap:
        gap_items = [g.strip() for g in payload.skill_gap.split(",") if g.strip()]
        for g in gap_items:
            # Check if skill exists
            skill_res = await db.execute(select(Skill).where(Skill.name.ilike(g)))
            existing_skill = skill_res.scalars().first()
            if not existing_skill:
                new_skill = Skill(
                    candidate_id=app.candidate_id,
                    name=g,
                    category="Technical",
                    current_level="Target / Gap",
                    evidence_source=f"Identified in feedback from application #{app.id}",
                    notes=f"Identified as gap: {payload.raw_feedback[:120] if payload.raw_feedback else ''}"
                )
                db.add(new_skill)

    await db.commit()
    await db.refresh(feedback)
    return feedback

@router.put("/{feedback_id}", response_model=FeedbackRead)
async def update_feedback(feedback_id: int, payload: dict, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Feedback).where(Feedback.id == feedback_id))
    feedback = result.scalars().first()
    if not feedback:
        raise HTTPException(status_code=404, detail="Feedback not found")

    for key, value in payload.items():
        if hasattr(feedback, key):
            setattr(feedback, key, value)

    await db.commit()
    await db.refresh(feedback)
    return feedback

@router.delete("/{feedback_id}")
async def delete_feedback(feedback_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Feedback).where(Feedback.id == feedback_id))
    feedback = result.scalars().first()
    if not feedback:
        raise HTTPException(status_code=404, detail="Feedback not found")
    await db.delete(feedback)
    await db.commit()
    return {"message": "Feedback deleted"}
