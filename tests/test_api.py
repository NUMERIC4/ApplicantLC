import os

# Tests must never load a user's local data or send it to a configured AI
# provider.  These overrides are set before importing the application.
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_applicant_lc.db"
os.environ["NVIDIA_API_KEY"] = ""

import pytest
from httpx import AsyncClient, ASGITransport
from backend.main import app
from backend.database import init_db

@pytest.mark.asyncio
async def test_health_and_dashboard():
    await init_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/api/health")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "healthy"
        assert data["app"] == "ApplicantLC"

        dash_res = await ac.get("/api/dashboard")
        assert dash_res.status_code == 200
        dash = dash_res.json()
        assert "metrics" in dash
        assert "daily_batch" in dash
        assert dash["metrics"]["companies_pool"] >= 1

@pytest.mark.asyncio
async def test_companies_and_applications_crud():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Create company
        comp_payload = {
            "name": "Tesla Automation GmbH",
            "city": "Berlin",
            "class_grade": "A",
            "recommended_effort": "Deep",
            "technical_field": "Robotics & Embedded Systems",
            "company_eligibility": "yes",
            "evidence_confidence": "High",
            "research_status": "Evaluating",
            "notes": "Testing company insertion"
        }
        c_res = await ac.post("/api/companies", json=comp_payload)
        assert c_res.status_code == 200
        comp_id = c_res.json()["id"]

        # Create application for this company
        app_payload = {
            "company_id": comp_id,
            "job_title": "Embedded Robotics Intern",
            "job_url": "https://tesla.example/jobs/1",
            "application_channel": "Direct",
            "status": "Applied",
            "current_stage": "Portal submitted",
            "notes": "Submitted with German cover letter"
        }
        a_res = await ac.post("/api/applications", json=app_payload)
        assert a_res.status_code == 200
        app_id = a_res.json()["id"]

        # Retrieve application
        get_app = await ac.get(f"/api/applications/{app_id}")
        assert get_app.status_code == 200
        assert get_app.json()["job_title"] == "Embedded Robotics Intern"

@pytest.mark.asyncio
async def test_ai_endpoints_fallback_and_extraction():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. AI Fit Evaluation
        fit_payload = {
            "company_name": "DeepRobotics AG",
            "job_title": "Python AI Vision Intern",
            "technical_field": "Computer Vision & Autonomous Robotics",
            "job_description": "We need strong Python, OpenCV, and PyTorch foundation."
        }
        fit_res = await ac.post("/api/ai/evaluate-fit", json=fit_payload)
        assert fit_res.status_code == 200
        fit_data = fit_res.json()
        assert fit_data["class_grade"] in ["A", "B", "B-/C", "C", "D"]
        assert fit_data["recommended_effort"] in ["Deep", "Medium+", "Medium", "Light", "Standard"]

        # 2. Extract feedback
        fb_payload = {
            "application_id": 1,
            "raw_feedback_text": "Thank you for applying. Unfortunately, your profile lacks hands-on Docker and Kubernetes experience.",
            "stage": "Recruiter review"
        }
        fb_res = await ac.post("/api/ai/extract-feedback", json=fb_payload)
        assert fb_res.status_code == 200
        fb_data = fb_res.json()
        assert fb_data["feedback_type"] in ["Skill gap", "Experience", "Language", "unknown"]
        assert len(fb_data["extracted_skill_gaps"]) >= 1
        assert "polite_feedback_response_draft" in fb_data

@pytest.mark.asyncio
async def test_sprint_and_learning_curve():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. Get today's batch
        batch_res = await ac.get("/api/daily-batches/today")
        assert batch_res.status_code == 200
        batch = batch_res.json()
        batch_id = batch["id"]

        # 2. Increment evaluation
        inc_res = await ac.post(f"/api/daily-batches/{batch_id}/increment-evaluation")
        assert inc_res.status_code == 200
        assert inc_res.json()["actual_evaluation"] >= 1

        # 3. Add skill
        skill_res = await ac.post("/api/skills", json={
            "name": "Rust Programming",
            "category": "Programming",
            "current_level": "Beginner",
            "evidence_source": "Rustlings exercises"
        })
        assert skill_res.status_code == 200
        assert skill_res.json()["name"] == "Rust Programming"

        # 4. Learning curve stats
        stats_res = await ac.get("/api/ai/learning-curve-stats")
        assert stats_res.status_code == 200
        stats = stats_res.json()
        assert stats["total_skills_tracked"] >= 1
        assert "conversion_by_class" in stats
