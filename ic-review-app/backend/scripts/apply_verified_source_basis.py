from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
STANDARD_PATH = BACKEND_ROOT / "app" / "data" / "standard_controls.json"
REVIEW_PATH = BACKEND_ROOT / "app" / "data" / "regulatory_corpus" / "standard_control_source_basis_review.json"
DB_PATH = BACKEND_ROOT / "data" / "ic_review.db"


def main() -> None:
    controls = json.loads(STANDARD_PATH.read_text(encoding="utf-8"))
    review_rows = json.loads(REVIEW_PATH.read_text(encoding="utf-8"))
    verified = {
        row["standard_code"]: row
        for row in review_rows
        if row.get("review_status") == "verified"
    }

    changed = 0
    for control in controls:
        row = verified.get(control.get("standard_code"))
        if not row:
            continue
        source_basis = row["proposed_source_basis"]
        external_regulation = source_basis.split("\uff1b", 1)[0]
        external_basis = row["evidence_excerpt"]
        if (
            control.get("source_basis") != source_basis
            or control.get("external_regulation") != external_regulation
            or control.get("external_basis") != external_basis
        ):
            control["source_basis"] = source_basis
            control["external_regulation"] = external_regulation
            control["external_basis"] = external_basis
            changed += 1

    STANDARD_PATH.write_text(json.dumps(controls, ensure_ascii=False, indent=2), encoding="utf-8")

    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        for code, row in verified.items():
            source_basis = row["proposed_source_basis"]
            external_regulation = source_basis.split("\uff1b", 1)[0]
            external_basis = row["evidence_excerpt"]
            conn.execute(
                """
                UPDATE standard_control_points
                   SET source_basis = ?,
                       external_regulation = ?,
                       external_basis = ?,
                       updated_at = ?
                 WHERE tenant_id = 'system'
                   AND standard_code = ?
                """,
                (source_basis, external_regulation, external_basis, now, code),
            )
        conn.commit()

    print(json.dumps({"verified": len(verified), "json_changed": changed, "db": str(DB_PATH)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
