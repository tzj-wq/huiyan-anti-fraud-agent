import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"

os.environ.setdefault("APP_ENV", "test")
os.environ["DATABASE_URL"] = "sqlite:///./huiyan_test.db"
os.environ["LLM_ENABLED"] = "false"

sys.path.insert(0, str(BACKEND_ROOT))

from app.core.database import Base, SessionLocal, engine, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import seed_demo_data  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def prepare_database():
    init_db()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_demo_data(db)
    finally:
        db.close()
    yield
    engine.dispose()


@pytest.fixture()
def db_session(prepare_database):
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def api_client(prepare_database):
    with TestClient(app) as client:
        yield client
