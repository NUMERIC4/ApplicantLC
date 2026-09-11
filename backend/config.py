import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    NVIDIA_API_KEY: str = ""
    NVIDIA_BASE_URL: str = "https://integrate.api.nvidia.com/v1"
    NVIDIA_MODEL_NAME: str = "nvidia/nemotron-3.5-lightning-30b-a3b"
    JOB_SOURCE_MAX_CHARS: int = 16000
    CV_MAX_FILE_MB: int = 10
    CV_SOURCE_MAX_CHARS: int = 40000
    APPLICANT_FILES_DIR: str = "data/applicant_files"
    NVIDIA_REQUEST_TIMEOUT_SECONDS: float = 110.0
    # Optional, comparison-only resume-parser spike. "local" remains normal flow.
    RESUME_PARSER_PROVIDER: str = "local"
    AFFINDA_API_KEY: str = ""
    AFFINDA_BASE_URL: str = "https://resume-parser.eu1.affinda.com"
    AFFINDA_REQUEST_TIMEOUT_SECONDS: float = 60.0
    DATABASE_URL: str = "sqlite+aiosqlite:///./applicant_lc.db"
    APP_HOST: str = "127.0.0.1"
    APP_PORT: int = 8000
    # Keep the application private by default.  Running with an external host is
    # an explicit opt-in and must be paired with authentication before use.
    DEBUG: bool = False

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
