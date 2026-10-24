"""Test-wide isolation for the application database.

Environment variables are set before application modules are imported so the
test suite never reads or mutates a developer's local demo database.
"""
import os
import shutil
import tempfile
from pathlib import Path

import pytest


_TEST_DIR = Path(tempfile.mkdtemp(prefix="coffee-assistant-tests-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_TEST_DIR / 'test.db').as_posix()}"
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")


@pytest.fixture(scope="session", autouse=True)
def _prepared_database():
    from app.models.base import Base
    from app.models.cafe import Member, Order, OrderItem, Product
    from app.models.database import engine
    from app.models.seed_cafe import seed_cafe
    from app.models.user import Conversation, User

    Base.metadata.create_all(bind=engine)
    seed_cafe()
    yield
    engine.dispose()
    shutil.rmtree(_TEST_DIR, ignore_errors=True)
