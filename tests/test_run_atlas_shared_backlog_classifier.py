from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from core.database import Database
from scripts.run_atlas_shared_backlog_classifier import run_backlog


class _StubResult:
    def __init__(self, payload: dict):
        self._payload = payload

    def to_dict(self) -> dict:
        return self._payload


class _StubSubsystem:
    def __init__(self, constitutions):
        self.constitutions = constitutions

    def classify(self, evidence, *, allow_surface_creation: bool = True):
        payload = {
            "paper_id": evidence.paper_id,
            "evidence_stage": "metadata_text",
            "article_type": {"value": "empirical_research", "confidence": 0.81, "source": "heuristic_classifier"},
            "intake_result": {
                "intake_decision": "accept_candidate",
                "routing_target": "article_eater",
                "domain_relevance": "on_domain",
                "primary_topic": "Lighting",
                "primary_bundle_id": "bundle-lighting-q-light",
                "topic_candidates": ["Lighting"],
                "matched_question_ids": ["Q-LIGHT"],
                "edge_case_kind": "none",
                "novelty_signal": 0.0,
                "topic_expansion_candidate": False,
                "new_topic_candidate": False,
                "proposed_topic_label": "",
                "adjacent_topics": [],
                "reasons": ["matched constitution"],
            },
            "question_summary": {
                "accepted_question_ids": ["Q-LIGHT"],
                "edge_case_question_ids": [],
                "reasons": ["matched constitution"],
            },
            "stable_topic_routing": {
                "primary_topic": "Lighting",
                "primary_bundle_id": "bundle-lighting-q-light",
                "candidates": [{"topic": "Lighting"}],
            },
            "analysis_steps_run": ["article_type", "constitutional_relevance", "stable_topic_routing"],
            "next_action": "ready_for_intake_decision",
            "needs_more_evidence": False,
            "overall_confidence": 0.81,
        }
        return _StubResult(payload)


def test_run_backlog_persists_shared_classification(monkeypatch, tmp_path: Path) -> None:
    db_path = tmp_path / "article_finder.db"
    Database(db_path)
    con = sqlite3.connect(db_path)
    con.execute(
        """
        INSERT INTO papers (
            paper_id, title, abstract, status, triage_decision, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """,
        ("p1", "Daylight and alertness", "Experiment on daylight and alertness.", "candidate", "pending"),
    )
    con.commit()
    con.close()

    import scripts.run_atlas_shared_backlog_classifier as mod

    monkeypatch.setattr(
        mod,
        "load_topic_constitution_bank",
        lambda: SimpleNamespace(version="v-test", source_path="atlas_shared:test", constitutions=()),
    )
    monkeypatch.setattr(mod, "AdaptiveClassifierSubsystem", _StubSubsystem)

    report_dir = tmp_path / "reports"
    stats = run_backlog(
        db_path=db_path,
        limit=10,
        require_abstract=True,
        only_pending=True,
        unclassified_only=True,
        allow_surface_creation=False,
        report_dir=report_dir,
    )

    assert stats["selected"] == 1
    assert stats["classified"] == 1
    assert stats["send_to_eater"] == 1

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    row = con.execute("SELECT * FROM papers WHERE paper_id='p1'").fetchone()
    con.close()

    assert row["triage_decision"] == "send_to_eater"
    assert row["topic_decision"] == "on_topic"
    assert row["atlas_article_type"] == "empirical_research"
    assert row["atlas_primary_topic"] == "Lighting"
    assert row["atlas_constitution_version"] == "v-test"
    assert row["atlas_classified_at"]
    assert json.loads(row["atlas_topic_candidates"]) == ["Lighting"]
    assert json.loads(row["atlas_matched_question_ids"]) == ["Q-LIGHT"]
    assert json.loads(row["atlas_classification_payload_json"])["overall_confidence"] == 0.81
    assert (report_dir / "latest_summary.json").exists()


def test_runner_script_help_executes() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [sys.executable, str(repo_root / "scripts" / "run_atlas_shared_backlog_classifier.py"), "--help"],
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    assert proc.returncode == 0
    assert "Run Atlas Shared backlog classification" in proc.stdout
