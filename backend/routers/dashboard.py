from datetime import date
from typing import Dict, Any, List
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from backend.database import get_db
from backend.models import (
    Company, Application, DailyBatch, Feedback, Interview, Skill, Candidate
)

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])

@router.get("")
async def get_dashboard_data(db: AsyncSession = Depends(get_db)):
    today = date.today()

    # 1. Total counts
    companies_count_q = await db.execute(select(func.count(Company.id)))
    companies_count = companies_count_q.scalar() or 0

    applications_total_q = await db.execute(select(func.count(Application.id)))
    applications_total = applications_total_q.scalar() or 0

    applied_today_q = await db.execute(
        select(func.count(Application.id)).where(Application.application_date == today)
    )
    applied_today = applied_today_q.scalar() or 0

    # Follow-ups due (follow_up_date <= today and still in active pipeline)
    follow_ups_due_q = await db.execute(
        select(func.count(Application.id)).where(
            Application.follow_up_date.isnot(None),
            Application.follow_up_date <= today,
            Application.status.in_(["Applied", "Preparing", "Response", "Interview"])
        )
    )
    follow_ups_due = follow_ups_due_q.scalar() or 0

    feedbacks_received_q = await db.execute(
        select(func.count(Feedback.id))
    )
    feedbacks_received = feedbacks_received_q.scalar() or 0

    interviews_q = await db.execute(
        select(func.count(Interview.id)).where(Interview.outcome.in_(["scheduled", "passed"]))
    )
    interviews_count = interviews_q.scalar() or 0

    offers_q = await db.execute(
        select(func.count(Application.id)).where(
            or_(Application.status == "offer", Application.current_stage == "Offer")
        )
    )
    offers_count = offers_q.scalar() or 0

    # 2. Get Today's Batch (or latest batch)
    batch_q = await db.execute(
        select(DailyBatch).where(DailyBatch.batch_date == today)
    )
    current_batch = batch_q.scalars().first()
    if not current_batch:
        # Check latest batch to compute day_no
        latest_batch_q = await db.execute(
            select(DailyBatch).order_by(DailyBatch.day_no.desc()).limit(1)
        )
        latest = latest_batch_q.scalars().first()
        next_day = (latest.day_no + 1) if latest else 1
        
        current_batch = DailyBatch(
            batch_date=today,
            day_no=next_day,
            target_evaluation=5,
            target_application=3,
            actual_evaluation=0,
            actual_application=applied_today,
            focus="Priority Companies & Follow-ups",
            status="in progress",
            notes="Daily sprint started"
        )
        db.add(current_batch)
        await db.commit()
        await db.refresh(current_batch)

    # 3. Today's active companies table (companies to review or evaluate today)
    active_companies_q = await db.execute(
        select(Company).order_by(Company.class_grade.asc()).limit(8)
    )
    active_companies = active_companies_q.scalars().all()
    companies_table = [
        {
            "id": c.id,
            "name": c.name,
            "city": c.city,
            "class": c.class_grade,
            "effort": c.recommended_effort,
            "technical_field": c.technical_field,
            "status": c.research_status,
            "eligibility": c.company_eligibility,
            "notes": c.notes or ""
        }
        for c in active_companies
    ]

    # 4. Learning Curve stats
    skills_q = await db.execute(select(Skill))
    skills = skills_q.scalars().all()
    
    feedbacks_q = await db.execute(select(Feedback))
    feedbacks = feedbacks_q.scalars().all()

    fb_types_dist = {}
    for fb in feedbacks:
        t = fb.feedback_type or "unknown"
        fb_types_dist[t] = fb_types_dist.get(t, 0) + 1

    # Stage breakdown for funnel
    apps_q = await db.execute(select(Application))
    all_apps = apps_q.scalars().all()
    stage_counts = {
        "Preparing": 0,
        "Applied": 0,
        "Interview": 0,
        "Offer": 0,
        "Rejected": 0
    }
    for app in all_apps:
        s = app.status or "Preparing"
        if s in stage_counts:
            stage_counts[s] += 1
        else:
            stage_counts["Applied"] += 1

    return {
        "metrics": {
            "companies_pool": companies_count,
            "applications_total": applications_total,
            "applied_today": applied_today,
            "day_no": current_batch.day_no if current_batch else 1,
            "open_follow_ups": follow_ups_due,
            "feedback_received": feedbacks_received,
            "interviews": interviews_count,
            "offers": offers_count
        },
        "daily_batch": {
            "id": current_batch.id if current_batch else None,
            "date": str(current_batch.batch_date) if current_batch else str(today),
            "day_no": current_batch.day_no if current_batch else 1,
            "target_evaluation": current_batch.target_evaluation if current_batch else 5,
            "target_application": current_batch.target_application if current_batch else 3,
            "actual_evaluation": current_batch.actual_evaluation if current_batch else 0,
            "actual_application": current_batch.actual_application if current_batch else 0,
            "focus": current_batch.focus if current_batch else "Target Pool",
            "status": current_batch.status if current_batch else "in progress",
            "notes": current_batch.notes or "",
            "next_pool": current_batch.next_pool or ""
        },
        "companies_table": companies_table,
        "pipeline_funnel": stage_counts,
        "feedback_types": fb_types_dist,
        "skills_count": len(skills)
    }
