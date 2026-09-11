import os

# Test collection must never inherit a developer's real NVIDIA credentials or
# production database, regardless of individual test-module import order.
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_applicant_lc.db"
os.environ["NVIDIA_API_KEY"] = ""
os.environ["AFFINDA_API_KEY"] = ""
