"""Integration test fixtures: SQLite in-memory DB + FastAPI test client."""
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.main import app, require_admin, require_user
from app.models import Season, SeasonState, User

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="function")
async def engine():
    """Fresh in-memory SQLite engine per test — creates and drops all tables."""
    from sqlalchemy.pool import StaticPool

    _engine = create_async_engine(
        TEST_DB_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield _engine
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await _engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db(engine):
    """AsyncSession for direct DB manipulation in tests."""
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def test_admin(db):
    user = User(
        google_id="admin-google-id",
        email="admin@test.com",
        name="Admin User",
        is_admin=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@pytest_asyncio.fixture
async def test_user(db):
    user = User(
        google_id="user-google-id",
        email="user@test.com",
        name="Regular User",
        is_admin=False,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@pytest_asyncio.fixture
async def extra_user(db):
    user = User(
        google_id="extra-google-id",
        email="extra@test.com",
        name="Extra User",
        is_admin=False,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@pytest_asyncio.fixture
async def active_season(db, test_admin):
    season = Season(name="Test Season", state=SeasonState.submit, page_limit=400)
    db.add(season)
    await db.commit()
    await db.refresh(season)
    return season


def make_client(engine, current_user):
    """Return an AsyncClient with DB and auth dependencies overridden."""
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_db():
        async with session_factory() as session:
            yield session

    async def override_user():
        return current_user

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_user] = override_user
    app.dependency_overrides[require_admin] = override_user

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest_asyncio.fixture
async def client_as_user(engine, test_user):
    """HTTP client authenticated as the regular test user."""
    async with make_client(engine, test_user) as c:
        yield c
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client_as_admin(engine, test_admin):
    """HTTP client authenticated as the admin test user."""
    async with make_client(engine, test_admin) as c:
        yield c
    app.dependency_overrides.clear()
