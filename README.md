# ApplicantLC — Applicant Learning Curve & AI Pipeline

> **An intelligent, feedback-informed career pipeline and skill adaptation engine powered by NVIDIA Open Models.**

[![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.14-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com)
[![NVIDIA NIM](https://img.shields.io/badge/NVIDIA%20NIM-Open%20Models-76B900.svg)](https://build.nvidia.com)
[![License](https://img.shields.io/badge/License-MIT-purple.svg)](LICENSE)

---

## 🎯 The Core Concept

Traditional job tracking tools (spreadsheets, standard Kanban boards) treat the job search as a passive numbers game. **ApplicantLC** transforms the process into a **closed-loop learning curve**:

```
[Target Discovery] ➔ [Daily Sprint Batch] ➔ [Fit & Class Grading (A-D)] ➔ [Application Submission]
        ▲                                                                       │
        │                                                                       ▼
[Skill Gap Closure] ◄── [NVIDIA Feedback Parser] ◄── [Polite Feedback Request] ◄── [Rejection]
```

1. **Daily Application Limit & Discipline**: Enforces daily target vs. actual goals for sustainable momentum.
2. **Multi-Variable Fit Grading (Class A–D)**: Computes suitability and recommends effort tiers (`Deep`, `Medium+`, `Medium`, `Light`, `Standard`).
3. **Relational Document Linker**: Tracks specific CV variants, tailored cover letters, and enrollment certificates (`Studienbescheinigung`) attached to each application.
4. **Proactive Feedback Request Protocol**: When facing rejection, systematically inquires about genuine employer expectations to signal a growth mindset to recruiters.
5. **NVIDIA Open Models Engine**: Automatically parses raw rejection messages into structured skill gaps, updates the candidate's learning curve, and generates professional feedback request emails.

---

## 🏗️ Architecture & Tech Stack

- **Backend**: Python 3.11+ / 3.14 with FastAPI, Pydantic v2, and SQLAlchemy (Async).
- **Database**: Local SQLite (`applicant_lc.db`) with zero-configuration automatic creation and demo seeding on first boot.
- **AI Engine**: NVIDIA NIM Open Models API (`https://integrate.api.nvidia.com/v1`) supporting:
  - `nvidia/nemotron-3.5-lightning-30b-a3b` *(Recommended NVIDIA-authored model)*
  - `nvidia/nemotron-3-nano-30b-a3b`
  - `nvidia/nemotron-4-340b-instruct`
  - *Includes an offline heuristic fallback mode when no API key is set.*
- **Frontend**: Responsive Single-Page Dashboard with a modern dark glassmorphism design system, dynamic Kanban board, and sprint trackers.

---

## 🚀 Quickstart Guide (Local Setup)

Anyone can run this project locally with **zero database configuration**:

### 1. Clone the repository
```bash
git clone https://github.com/YourUsername/ApplicantLC.git
cd ApplicantLC
```

### 2. Install dependencies
Using [`uv`](https://docs.astral.sh/uv/) (recommended):
```bash
uv sync
```
*Or standard pip:*
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -e .
```

### 3. Start the application
```bash
uv run uvicorn backend.main:app --reload --port 8000
```
Open **[http://127.0.0.1:8000](http://127.0.0.1:8000)** in your browser.

> [!TIP]
> **Automatic Database Creation**: On the very first launch, SQLite automatically creates `applicant_lc.db` locally and seeds realistic demo data so evaluators and judges can immediately test the entire workflow without manual setup.

---

## 🤖 Configuring NVIDIA Open Models

1. Get a free API key with 1,000 complimentary credits at [build.nvidia.com](https://build.nvidia.com/).
2. Copy `.env.example` to `.env` and set the backend-only key:
     ```env
     NVIDIA_API_KEY="nvapi-your-key-here"
     NVIDIA_MODEL_NAME="nvidia/nemotron-3.5-lightning-30b-a3b"
     ```
3. *Note: If no API key is provided, the system automatically uses its offline heuristic engine so that all features remain testable.*

---

## 🔒 Security & Privacy Architecture

- **Data Sovereignty**: The database (`applicant_lc.db`) remains 100% on the user's local machine and is protected by `.gitignore` so personal job applications, grades, and notes are never leaked to GitHub.
- **API Key Protection**: Secrets in `.env` are excluded from version control and are loaded only by the backend. The dashboard can report configuration status but cannot view, enter, or update the key.
- **Local-only access**: The server binds to `127.0.0.1` by default and does not enable cross-origin API access. Do not expose it to a network without adding authentication.
- **AI processing notice**: AI analysis sends only the information in the selected analysis request (for example, a job description or feedback text, plus the locally stored candidate summary and skills for fit analysis) to NVIDIA NIM. Remove personal details you do not want to share before submitting an AI request.

## Optional Affinda Resume Parser Comparison

The default CV flow remains `PDF → local layout parser → NVIDIA extraction → review`.
Affinda is an optional, non-persistent comparison spike and is not the production/default parser.

To enable the explicit **Compare with Affinda** action, set backend-only values in `.env`:

```env
RESUME_PARSER_PROVIDER=local
AFFINDA_API_KEY="your-affinda-key"
AFFINDA_BASE_URL="https://resume-parser.eu1.affinda.com"
AFFINDA_REQUEST_TIMEOUT_SECONDS=60
```

The comparison action sends the selected original PDF to the configured Affinda endpoint once, after browser confirmation. It returns a transient normalized preview and does not change the saved document, CV review, parser version, hashes, or confirmation state.

---

## 🗺️ Project Roadmap (Future Phases)

- [ ] **Multi-User Authentication**: JWT / OAuth2 integration (Sign in with Google / GitHub / LinkedIn).
- [ ] **Multi-Tenant Cloud DB**: PostgreSQL / Supabase adapter for cloud sync across devices.
- [ ] **Coach / University Portal**: Mentor view allowing university career services to guide students on their learning curve.
- [ ] **Automatic Job Portal Scraper**: Headless background fetching for configured search alerts.

---

## 🧪 Testing

Run the automated test suite:
```bash
uv run pytest -v
```

---

## 📄 License
MIT License. Built for developer portfolios and innovation competitions.
