from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from backend.database import get_db
from backend.models import Company, CompanyRequirement, Application
from backend.schemas import (
    CompanyCreate, CompanyRead, CompanyUpdate,
    CompanyRequirementCreate, CompanyRequirementRead
)

router = APIRouter(prefix="/api/companies", tags=["Companies"])

@router.get("", response_model=List[CompanyRead])
async def list_companies(
    class_grade: Optional[str] = Query(None),
    technical_field: Optional[str] = Query(None),
    eligibility: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    query = select(Company)
    if class_grade:
        query = query.where(Company.class_grade == class_grade)
    if technical_field:
        query = query.where(Company.technical_field.ilike(f"%{technical_field}%"))
    if eligibility:
        query = query.where(Company.company_eligibility == eligibility)
    if search:
        query = query.where(
            or_(
                Company.name.ilike(f"%{search}%"),
                Company.city.ilike(f"%{search}%"),
                Company.technical_field.ilike(f"%{search}%"),
                Company.notes.ilike(f"%{search}%")
            )
        )
    query = query.order_by(Company.class_grade.asc(), Company.name.asc())
    result = await db.execute(query)
    return result.scalars().all()

@router.post("", response_model=CompanyRead)
async def create_company(payload: CompanyCreate, db: AsyncSession = Depends(get_db)):
    company = Company(**payload.model_dump())
    db.add(company)
    await db.commit()
    await db.refresh(company)
    return company

@router.get("/{company_id}", response_model=CompanyRead)
async def get_company(company_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Company).where(Company.id == company_id))
    company = result.scalars().first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return company

@router.put("/{company_id}", response_model=CompanyRead)
async def update_company(company_id: int, payload: CompanyUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Company).where(Company.id == company_id))
    company = result.scalars().first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(company, key, value)

    await db.commit()
    await db.refresh(company)
    return company

@router.delete("/{company_id}")
async def delete_company(company_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Company).where(Company.id == company_id))
    company = result.scalars().first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    await db.delete(company)
    await db.commit()
    return {"message": "Company deleted successfully"}

# Requirements sub-routes
@router.get("/{company_id}/requirements", response_model=List[CompanyRequirementRead])
async def get_company_requirements(company_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(CompanyRequirement).where(CompanyRequirement.company_id == company_id))
    return result.scalars().all()

@router.post("/{company_id}/requirements", response_model=CompanyRequirementRead)
async def add_company_requirement(company_id: int, payload: CompanyRequirementCreate, db: AsyncSession = Depends(get_db)):
    req = CompanyRequirement(**payload.model_dump())
    req.company_id = company_id
    db.add(req)
    await db.commit()
    await db.refresh(req)
    return req
