from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from scripts.repair_af_semantic_state import repair


def _init_db(db_path: Path) -> None:
    con = sqlite3.connect(db_path)
    con.executescript(
        """
        CREATE TABLE papers (
            paper_id TEXT PRIMARY KEY,
            status TEXT,
            triage_decision TEXT,
            triage_score REAL,
            ingest_method TEXT,
            abstract TEXT,
            pdf_path TEXT,
            ae_job_path TEXT,
            ae_output_path TEXT,
            ae_status TEXT,
            ae_run_id TEXT,
            ae_n_claims INTEGER,
            ae_n_rules INTEGER,
            ae_confidence REAL,
            human_notes TEXT,
            updated_at TEXT
        );
        """
    )
    con.commit()
    con.close()


def test_repair_normalizes_semantic_state(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "ae_outputs" / "out1").mkdir(parents=True)
    ((tmp_path / "data" / "ae_outputs" / "out1") / "result.json").write_text(
        json.dumps(
            {
                "status": "PARTIAL_SUCCESS",
                "run_id": "ae.run.test",
                "summary": {"n_claims": 1, "n_rules": 2},
                "quality": {"confidence": 0.25},
            }
        ),
        encoding="utf-8",
    )
    db_path = tmp_path / "data" / "article_finder.db"
    _init_db(db_path)

    con = sqlite3.connect(db_path)
    con.execute(
        "INSERT INTO papers VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "p1",
            "candidate",
            "needs_review",
            0.8,
            "manual",
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        ),
    )
    con.execute(
        "INSERT INTO papers VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "p2",
            "candidate",
            "review",
            0.8,
            "manual",
            None,
            None,
            "data/ae_jobs/job1",
            "data/ae_outputs/out1",
            "pending",
            None,
            None,
            None,
            None,
            None,
            None,
        ),
    )
    con.execute(
        "INSERT INTO papers VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "p3",
            "candidate",
            "send_to_eater",
            0.9,
            "manual",
            None,
            None,
            "data/ae_jobs/job2",
            None,
            "SUCCESS",
            None,
            4,
            5,
            0.8,
            "already noted",
            None,
        ),
    )
    con.commit()
    con.close()

    stats = repair(db_path, repo_root=tmp_path)
    assert stats["triage_needs_review_normalized"] == 1
    assert stats["ae_pending_promoted_from_result"] == 1
    assert stats["ae_stale_terminal_downgraded_to_pending"] == 1

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    rows = {
        row["paper_id"]: dict(row)
        for row in con.execute("SELECT * FROM papers").fetchall()
    }
    con.close()

    assert rows["p1"]["triage_decision"] == "review"
    assert rows["p2"]["ae_status"] == "PARTIAL_SUCCESS"
    assert rows["p2"]["ae_run_id"] == "ae.run.test"
    assert rows["p2"]["ae_n_claims"] == 1
    assert rows["p2"]["ae_n_rules"] == 2
    assert rows["p3"]["ae_status"] == "pending"
    assert rows["p3"]["ae_output_path"] is None
    assert rows["p3"]["ae_run_id"] is None
    assert "Downgraded stale terminal ae_status" in rows["p3"]["human_notes"]
