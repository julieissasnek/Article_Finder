from __future__ import annotations

import sqlite3
from pathlib import Path

from core.database import Database
from scripts.verify_af_shared_intake_classification import gather_metrics


def test_verify_af_shared_intake_classification_detects_bad_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "article_finder.db"
    Database(db_path)
    con = sqlite3.connect(db_path)
    con.execute(
        """
        INSERT INTO papers (
            paper_id, title, status, triage_decision,
            atlas_constitution_version, atlas_article_type, atlas_evidence_stage,
            atlas_intake_decision, atlas_routing_target, atlas_domain_relevance,
            atlas_topic_candidates, atlas_matched_question_ids, atlas_adjacent_topics,
            atlas_topic_expansion_candidate, atlas_new_topic_candidate, atlas_needs_more_evidence,
            atlas_article_type_confidence, atlas_overall_confidence, atlas_novelty_signal,
            atlas_classification_payload_json, atlas_classified_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """,
        (
            "p1",
            "Bad row",
            "candidate",
            "pending",
            "",
            "empirical_research",
            "metadata_text",
            "accept_candidate",
            "article_eater",
            "on_domain",
            "not-json",
            "[]",
            "[]",
            2,
            0,
            0,
            1.2,
            0.9,
            0.0,
            "[]",
        ),
    )
    con.commit()
    con.close()

    metrics = gather_metrics(db_path)

    assert metrics["atlas_classified_rows"] == 1
    assert metrics["missing_core_rows"] == 1
    assert metrics["bad_topic_candidates_rows"] == 1
    assert metrics["bad_boolean_rows"] == 1
    assert metrics["bad_confidence_rows"] == 1
    assert metrics["bad_payload_rows"] == 1
    assert metrics["on_domain_missing_primary_topic_rows"] == 1
    assert metrics["missing_last_mile_rows"] == 1
