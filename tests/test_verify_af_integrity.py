from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from scripts.verify_af_integrity import gather_metrics


def test_gather_metrics_detects_integrity_failures(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "pdfs").mkdir()
    db_path = tmp_path / "data" / "article_finder.db"
    con = sqlite3.connect(db_path)
    con.executescript(
        """
        CREATE TABLE papers (
            paper_id TEXT PRIMARY KEY,
            pdf_path TEXT,
            pdf_sha256 TEXT,
            ae_job_path TEXT,
            ae_output_path TEXT,
            abstract TEXT
        );
        CREATE TABLE expansion_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            status TEXT
        );
        """
    )
    (tmp_path / "data" / "pdfs" / "orphan.pdf").write_text("x")
    good_pdf = tmp_path / "data" / "good.pdf"
    good_pdf.write_text("x")
    good_sha = hashlib.sha256(good_pdf.read_bytes()).hexdigest()
    con.execute(
        "INSERT INTO papers VALUES (?,?,?,?,?,?)",
        ("p1", "data/good.pdf", good_sha, "missing/job", "missing/out", "abs"),
    )
    con.execute(
        "INSERT INTO papers VALUES (?,?,?,?,?,?)",
        ("p2", "data/missing.pdf", "sha1", None, None, None),
    )
    bad_pdf = tmp_path / "data" / "bad.pdf"
    bad_pdf.write_text("y")
    con.execute(
        "INSERT INTO papers VALUES (?,?,?,?,?,?)",
        ("p3", "data/bad.pdf", good_sha, None, None, None),
    )
    con.execute("INSERT INTO expansion_queue(status) VALUES ('pending')")
    con.commit()
    con.close()

    from scripts import verify_af_integrity as mod
    old_root = mod.REPO_ROOT
    try:
        mod.REPO_ROOT = tmp_path
        metrics = gather_metrics(db_path)
    finally:
        mod.REPO_ROOT = old_root

    assert metrics["missing_pdf_path_files"] == 1
    assert metrics["pdf_sha256_mismatch_rows"] == 1
    assert metrics["duplicate_pdf_sha_rows"] == 1
    assert metrics["orphan_pdf_files"] == 1
    assert metrics["missing_ae_job_paths"] == 1
    assert metrics["missing_ae_output_paths"] == 1
