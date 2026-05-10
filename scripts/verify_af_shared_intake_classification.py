#!/usr/bin/env python3
"""Verify AF Atlas Shared intake-classification persistence."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DB_PATH = REPO_ROOT / "data" / "article_finder.db"


def _loads_json(text: str | None) -> Any:
    if text is None or not str(text).strip():
        return []
    return json.loads(text)


def gather_metrics(db_path: Path = DB_PATH) -> dict[str, Any]:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    rows = list(
        con.execute(
            """
            SELECT *
            FROM papers
            WHERE atlas_classified_at IS NOT NULL AND TRIM(atlas_classified_at) != ''
            """
        ).fetchall()
    )
    missing_core = 0
    bad_topic_candidates = 0
    bad_question_ids = 0
    bad_adjacent_topics = 0
    bad_payload = 0
    bad_booleans = 0
    bad_confidence = 0
    on_domain_missing_primary_topic = 0
    missing_last_mile = 0
    for row in rows:
        if not all(
            str(row[key] or "").strip()
            for key in (
                "atlas_constitution_version",
                "atlas_article_type",
                "atlas_evidence_stage",
                "atlas_intake_decision",
                "atlas_routing_target",
                "atlas_next_action",
            )
        ):
            missing_core += 1

        for key, counter_name in (
            ("atlas_topic_candidates", "bad_topic_candidates"),
            ("atlas_matched_question_ids", "bad_question_ids"),
            ("atlas_adjacent_topics", "bad_adjacent_topics"),
        ):
            try:
                value = _loads_json(row[key])
                if not isinstance(value, list):
                    raise ValueError("not a list")
            except Exception:
                if counter_name == "bad_topic_candidates":
                    bad_topic_candidates += 1
                elif counter_name == "bad_question_ids":
                    bad_question_ids += 1
                else:
                    bad_adjacent_topics += 1

        try:
            payload = _loads_json(row["atlas_classification_payload_json"])
            if not isinstance(payload, dict):
                raise ValueError("not an object")
        except Exception:
            bad_payload += 1

        if row["atlas_topic_expansion_candidate"] not in (0, 1) or row["atlas_new_topic_candidate"] not in (0, 1) or row["atlas_needs_more_evidence"] not in (0, 1):
            bad_booleans += 1

        for key in ("atlas_article_type_confidence", "atlas_overall_confidence", "atlas_novelty_signal"):
            value = row[key]
            if value is None:
                continue
            if not (0.0 <= float(value) <= 1.0):
                bad_confidence += 1
                break

        if row["atlas_domain_relevance"] == "on_domain" and not str(row["atlas_primary_topic"] or "").strip():
            on_domain_missing_primary_topic += 1

        topic_category = str(row["topic_category"] or "").strip()
        last_mile_missing = not all(
            str(row[key] or "").strip()
            for key in ("triage_decision", "topic_decision", "topic_stage", "status")
        )
        if row["atlas_domain_relevance"] == "on_domain" and topic_category != str(row["atlas_primary_topic"] or "").strip():
            last_mile_missing = True
        if last_mile_missing:
            missing_last_mile += 1

    metrics = {
        "atlas_classified_rows": len(rows),
        "missing_core_rows": missing_core,
        "bad_topic_candidates_rows": bad_topic_candidates,
        "bad_question_ids_rows": bad_question_ids,
        "bad_adjacent_topics_rows": bad_adjacent_topics,
        "bad_payload_rows": bad_payload,
        "bad_boolean_rows": bad_booleans,
        "bad_confidence_rows": bad_confidence,
        "on_domain_missing_primary_topic_rows": on_domain_missing_primary_topic,
        "missing_last_mile_rows": missing_last_mile,
    }
    con.close()
    return metrics


def main() -> int:
    metrics = gather_metrics()
    hard_zero = [
        "missing_core_rows",
        "bad_topic_candidates_rows",
        "bad_question_ids_rows",
        "bad_adjacent_topics_rows",
        "bad_payload_rows",
        "bad_boolean_rows",
        "bad_confidence_rows",
        "on_domain_missing_primary_topic_rows",
        "missing_last_mile_rows",
    ]
    failures = [key for key in hard_zero if metrics[key] != 0]
    payload = {
        "status": "ok" if not failures else "fail",
        "failures": failures,
        "metrics": metrics,
    }
    print(json.dumps(payload, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
