from collections.abc import Generator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

settings = get_settings()

connect_args: dict = {}
if settings.database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False, "timeout": 30}

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    pool_pre_ping=True,
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_connection, _connection_record) -> None:
    if not settings.database_url.startswith("sqlite"):
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    if settings.database_url.startswith("sqlite"):
        desired = {
            "documents": {
                "tenant_id": "VARCHAR(64) DEFAULT 'default'", "org_id": "VARCHAR(64) DEFAULT 'default'",
                "lock_status": "VARCHAR(32) DEFAULT 'unlocked'", "quality_status": "VARCHAR(32) DEFAULT 'normal'",
                "parse_error_code": "VARCHAR(64) DEFAULT ''", "parse_error_detail": "TEXT DEFAULT ''",
                "degradation_notes": "TEXT DEFAULT ''", "ocr_confidence": "FLOAT", "page_count": "INTEGER",
                "file_size": "INTEGER DEFAULT 0", "content_hash": "VARCHAR(64) DEFAULT ''",
                "table_review_required": "BOOLEAN DEFAULT 0", "complex_table_pages": "VARCHAR(255) DEFAULT ''",
            },
            "review_tasks": {
                "task_type": "VARCHAR(32) DEFAULT 'group_vs_subsidiary'",
                "execution_mode": "VARCHAR(32) DEFAULT 'hybrid'", "executor_backend": "VARCHAR(32) DEFAULT 'local_thread'",
                "prompt_bundle_version": "VARCHAR(64) DEFAULT 'Hybrid_V1.0'", "core_model_version": "VARCHAR(128) DEFAULT ''",
                "expert_model_version": "VARCHAR(128) DEFAULT ''", "result_version": "INTEGER DEFAULT 1",
                "degradation_reason": "TEXT DEFAULT ''",
                "reference_template_id": "VARCHAR(64) DEFAULT ''", "reference_template_title": "VARCHAR(255) DEFAULT ''",
            },
            "differences": {
                "original_ai_reason": "TEXT DEFAULT ''", "fallback_reason": "TEXT DEFAULT ''",
                "prompt_version": "VARCHAR(64) DEFAULT 'CoreAnalyser_V1.0'", "model_version": "VARCHAR(128) DEFAULT ''",
                "group_external_regulation": "TEXT DEFAULT ''", "group_external_basis": "TEXT DEFAULT ''",
            },
            "standard_control_points": {
                "external_regulation": "TEXT DEFAULT ''", "external_basis": "TEXT DEFAULT ''",
            },
            "analysis_cache": {
                "global_context_hash": "VARCHAR(64) DEFAULT ''", "dependency_scope": "VARCHAR(32) DEFAULT 'document'",
            },
            "exemption_rules": {
                "base_document_id": "INTEGER", "base_version": "VARCHAR(64) DEFAULT ''",
                "base_control_fingerprint": "TEXT DEFAULT ''", "governance_note": "TEXT DEFAULT ''",
            },
            "supplement_requests": {
                "pollution_scan_result": "TEXT DEFAULT ''", "derived_difference_ids": "VARCHAR(255) DEFAULT ''",
            },
        }
        inspector = inspect(engine)
        with engine.begin() as conn:
            for table_name, cols in desired.items():
                if table_name not in inspector.get_table_names():
                    continue
                existing = {c["name"] for c in inspector.get_columns(table_name)}
                for name, ddl in cols.items():
                    if name not in existing:
                        conn.execute(text(f'ALTER TABLE "{table_name}" ADD COLUMN "{name}" {ddl}'))
