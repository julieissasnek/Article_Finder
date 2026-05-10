from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from scripts.verify_af_semantic_integrity import gather_metrics


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
            human_notes TEXT
        );
        """
    )
    con.commit()
    con.close()


def test_gather_metrics_detects_semantic_drift(tmp_path: Path) -> None:
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
        "INSERT INTO papers VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "p_valid",
            "candidate",
            "pending",
            0.5,
            "bibliographer",
            "abs",
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
        "INSERT INTO papers VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "p_deprecated",
            "candidate",
            "needs_review",
            0.9,
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
        ),
    )
    con.execute(
        "INSERT INTO papers VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "p_stale_pending",
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
        ),
    )
    con.execute(
        "INSERT INTO papers VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "p_stale_success",
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
            None,
            None,
            None,
            None,
        ),
    )
    con.commit()
    con.close()

    metrics = gather_metrics(db_path, repo_root=tmp_path)

    assert metrics["deprecated_triage_rows"] == 1
    assert metrics["ae_pending_with_output_rows"] == 1
    assert metrics["ae_result_status_mismatch_rows"] == 1
    assert metrics["ae_terminal_without_output_rows"] == 1

