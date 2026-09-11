import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from backend.config import settings
from backend.database import init_db
from backend.routers import (
    dashboard, companies, applications, daily_batches,
    feedbacks, documents, interviews, skills, candidates,
    search_alerts, ai, jobs
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize DB tables and seed data
    await init_db()
    yield

app = FastAPI(
    title="ApplicantLC - Applicant Learning Curve System",
    description="Pipeline management, feedback loops, and intelligent skill adaptation with NVIDIA Open Models",
    version="1.0.0",
    lifespan=lifespan
)

@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    # This app serves its UI and API from the same local origin.  Do not allow
    # other sites to read or mutate an applicant's local data.
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "connect-src 'self'; "
        "img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline'; "
        "font-src 'self'; "
        "script-src 'self'; "
        "base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
    )
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Cache-Control"] = "no-store"
    return response

# Register API Routers
app.include_router(dashboard.router)
app.include_router(companies.router)
app.include_router(applications.router)
app.include_router(daily_batches.router)
app.include_router(feedbacks.router)
app.include_router(documents.router)
app.include_router(interviews.router)
app.include_router(skills.router)
app.include_router(candidates.router)
app.include_router(search_alerts.router)
app.include_router(ai.router)
app.include_router(jobs.router)

# Mount frontend directory for static assets
frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

    @app.get("/")
    async def serve_index():
        return FileResponse(os.path.join(frontend_dir, "index.html"))

@app.get("/api/health")
async def health():
    return {
        "status": "healthy",
        "app": "ApplicantLC",
        "nvidia_model": settings.NVIDIA_MODEL_NAME,
        "database": "connected"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host=settings.APP_HOST, port=settings.APP_PORT, reload=settings.DEBUG)
