import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["AUTO_SEED"] = "false"
os.environ["PDF_PARSER_PROVIDER"] = "local"

from app.db import Base, get_db  # noqa: E402
from app import db as db_module  # noqa: E402
from app.main import app  # noqa: E402

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(bind=engine)
db_module.engine = engine
db_module.SessionLocal = TestSession


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    session = TestSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db):
    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def fake_llm_responses():
    diff_payload = {
        "differences": [
            {
                "pair_index": 0,
                "diff_type": "越权",
                "risk_level": "高",
                "summary": "审批权限超出集团授权",
                "ai_reason": "子公司审批上限高于集团要求。",
                "suggestion": "调整为超过200万元须报集团审批。",
                "confidence": 0.9,
            }
        ]
    }
    expert_payload = {
        "review_summary": "经国企内控专家复核后保留。",
        "items": [
            {
                "diff_index": 0,
                "keep": True,
                "diff_type": "越权",
                "risk_level": "高",
                "summary": "采购审批权限：子公司自主审批阈值高于集团授权边界",
                "ai_reason": "集团要求超过200万元须集团审批，子公司制度存在授权边界上移。",
                "suggestion": "建议将子公司制度调整为超过200万元须报集团审批，并明确例外审批流程。",
                "confidence": 0.92,
                "audit_comment": "属于集团授权管控边界问题，应保留高风险结论。",
            }
        ],
    }
    return {
        "Core Analyser": diff_payload,
        "内控制度比对": diff_payload,
        "国企内控专家复核": expert_payload,
        "default": {"differences": [], "items": []},
    }
