from datetime import date
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from backend.database import get_db
from backend.models import Application, Company, DailyBatch, ApplicationDocument, Document
from backend.schemas import (
    ApplicationCreate, ApplicationRead, ApplicationUpdate,
    ApplicationDocumentCreate, ApplicationDocumentRead
)

router = APIRouter(prefix="/api/applications", tags=["Applications"])

@router.get("", response_model=List[ApplicationRead])
async def list_applications(
    status: Optional[str] = Query(None),
    stage: Optional[str] = Query(None),
    company_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    query = select(Application).options(
        selectinload(Application.company),
        selectinload(Application.application_documents).selectinload(ApplicationDocument.document)
    )
    if status:
        query = query.where(Application.status == status)
    if stage:
        query = query.where(Application.current_stage == stage)
    if company_id:
        query = query.where(Application.company_id == company_id)

    query = query.order_by(Application.application_date.desc(), Application.id.desc())
    result = await db.execute(query)
    return result.scalars().all()

@router.post("", response_model=ApplicationRead)
async def create_application(payload: ApplicationCreate, db: AsyncSession = Depends(get_db)):
    # Verify company exists
    company_res = await db.execute(select(Company).where(Company.id == payload.company_id))
    company = company_res.scalars().first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    app_data = payload.model_dump(exclude={"attached_documents"})
    app = Application(**app_data)
    
    # Inherit company class and effort if not set
    if not app.company_class:
        app.company_class = company.class_grade
    if not app.company_recommended_effort:
        app.company_recommended_effort = company.recommended_effort

    # Link to today's batch if not explicitly set
    if not app.daily_batch_id:
        today_batch_res = await db.execute(
            select(DailyBatch).where(DailyBatch.batch_date == date.today())
        )
        today_batch = today_batch_res.scalars().first()
        if today_batch:
            app.daily_batch_id = today_batch.id
            today_batch.actual_application += 1

    db.add(app)
    await db.flush()

    # Attach documents if provided
    if payload.attached_documents:
        for doc_item in payload.attached_documents:
            app_doc = ApplicationDocument(
                application_id=app.id,
                document_id=doc_item.document_id,
                document_role=doc_item.document_role or "Primary CV",
                notes=doc_item.notes
            )
            db.add(app_doc)

    # If company status was evaluating, update to applied
    if app.status in ["Applied", "Ready", "Interview"]:
        company.research_status = "Applied"

    await db.commit()

    # Reload with relationships
    result = await db.execute(
        select(Application)
        .options(
            selectinload(Application.company),
            selectinload(Application.application_documents).selectinload(ApplicationDocument.document)
        )
        .where(Application.id == app.id)
    )
    return result.scalars().first()

@router.get("/{application_id}", response_model=ApplicationRead)
async def get_application(application_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Application)
        .options(
            selectinload(Application.company),
            selectinload(Application.application_documents).selectinload(ApplicationDocument.document)
        )
        .where(Application.id == application_id)
    )
    app = result.scalars().first()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    return app

@router.put("/{application_id}", response_model=ApplicationRead)
async def update_application(application_id: int, payload: ApplicationUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Application)
        .options(
            selectinload(Application.company),
            selectinload(Application.application_documents).selectinload(ApplicationDocument.document)
        )
        .where(Application.id == application_id)
    )
    app = result.scalars().first()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(app, key, value)

    await db.commit()
    await db.refresh(app)
    return app

@router.delete("/{application_id}")
async def delete_application(application_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Application).where(Application.id == application_id))
    app = result.scalars().first()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    await db.delete(app)
    await db.commit()
    return {"message": "Application deleted successfully"}

# Attach document endpoint
@router.post("/{application_id}/documents", response_model=ApplicationDocumentRead)
async def attach_document(
    application_id: int,
    payload: ApplicationDocumentCreate,
    db: AsyncSession = Depends(get_db)
):
    app_doc = ApplicationDocument(
        application_id=application_id,
        document_id=payload.document_id,
        document_role=payload.document_role or "Primary CV",
        notes=payload.notes
    )
    db.add(app_doc)
    await db.commit()
    
    res = await db.execute(
        select(ApplicationDocument)
        .options(selectinload(ApplicationDocument.document))
        .where(ApplicationDocument.id == app_doc.id)
    )
    return res.scalars().first()
