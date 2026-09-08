"""
Shared pytest fixtures: an isolated in-memory SQLite DB per test, wired into
the FastAPI app via a `get_db` dependency override, plus a pre-created user
and its auth headers for protected routes.

The `client` fixture never enters the app's lifespan (no `with TestClient(...)`),
so `init_db()`/`seed_database()`/the APScheduler never touch the real
`news_summary.db` or start background jobs during tests.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.db.database import Base, get_db
from app.db import crud
from app.core.security import hash_password, create_access_token
from app.main import app


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client(db_session):
    def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture()
def test_user(db_session):
    return crud.create_user(
        db=db_session,
        email="tester@example.com",
        hashed_password=hash_password("testpass123"),
        role="user",
    )


@pytest.fixture()
def auth_headers(test_user):
    token = create_access_token(
        {"sub": str(test_user.id), "email": test_user.email, "role": test_user.role}
    )
    return {"Authorization": f"Bearer {token}"}
