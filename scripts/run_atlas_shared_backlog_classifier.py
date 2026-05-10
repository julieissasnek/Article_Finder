#!/usr/bin/env python3
"""Run Atlas Shared pre-extraction classification over the AF backlog."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, UTC
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
ATLAS_SHARED_SRC_CANDIDATES = (
    REPO_ROOT.parent / "Atlas_Shared" / "src",
    REPO_ROOT.parent / "atlas_shared" / "src",
)
for path in ATLAS_SHARED_SRC_CANDIDATES:
    if path.exists() and str(path) not in sys.path:
        sys.path.insert(0, str(path))

from atlas_shared.classifier_system import AdaptiveClassifierSubsystem, ClassificationEvidence
from atlas_shared.topic_bank import TopicConstitutionBank, load_topic_constitution_bank

from core.database import Database


DEFAULT_DB_PATH = REPO_ROOT / "data" / "article_finder.db"
DEFAULT_REPORT_DIR = REPO_ROOT / "data" / "classification_reports" / "atlas_shared_backlog"


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _recommended_triage_decision(payload: dict[str, Any]) -> str:
    intake = payload.get("intake_result") or {}
    decision = intake.get("intake_decision")
    if decision == "accept_candidate":
        return "send_to_eater"
    if decision in {"edge_case", "manual_review"}:
        return "review"
    if decision == "reject_clear_false_positive":
        return "reject"
    return "pending"


def _coarse_topic_decision(payload: dict[str, Any]) -> str:
    intake = payload.get("intake_result") or {}
    domain_relevance = intake.get("domain_relevance")
    if domain_relevance == "on_domain":
        return "on_topic"
    if domain_relevance == "clear_false_positive":
        return "off_topic"
    if domain_relevance == "insufficient_metadata":
        return "needs_abstract"
    return "possibly_off_topic"


def _candidate_topics(payload: dict[str, Any]) -> list[str]:
    intake = payload.get("intake_result") or {}
    candidates = intake.get("topic_candidates")
    if isinstance(candidates, list):
        return [str(item) for item in candidates if str(item).strip()]
    routing = payload.get("stable_topic_routing") or {}
    out: list[str] = []
    for item in routing.get("candidates") or []:
        topic = str(item.get("topic") or "").strip()
        if topic:
            out.append(topic)
    return out


def _matched_question_ids(payload: dict[str, Any]) -> list[str]:
    intake = payload.get("intake_result") or {}
    ids = intake.get("matched_question_ids")
    if isinstance(ids, list):
        return [str(item) for item in ids if str(item).strip()]
    summary = payload.get("question_summary") or {}
    return [
        *[str(item) for item in summary.get("accepted_question_ids") or [] if str(item).strip()],
        *[str(item) for item in summary.get("edge_case_question_ids") or [] if str(item).strip()],
    ]


def _adjacent_topics(payload: dict[str, Any]) -> list[str]:
    intake = payload.get("intake_result") or {}
    values = intake.get("adjacent_topics") or []
    return [str(item) for item in values if str(item).strip()]


def build_update_fields(
    paper: dict[str, Any],
    payload: dict[str, Any],
    *,
    bank: TopicConstitutionBank,
    classified_at: str,
) -> dict[str, Any]:
    article_type = payload.get("article_type") or {}
    intake = payload.get("intake_result") or {}
    triage_decision = _recommended_triage_decision(payload)
    topic_decision = _coarse_topic_decision(payload)
    current_status = str(paper.get("status") or "candidate")
    new_status = current_status
    if triage_decision == "reject":
        new_status = "rejected"
    elif current_status == "pending_scorer" and triage_decision in {"send_to_eater", "review"}:
        new_status = "candidate"

    reasons = intake.get("reasons") or (payload.get("question_summary") or {}).get("reasons") or []
    candidate_topics = _candidate_topics(payload)
    matched_question_ids = _matched_question_ids(payload)
    adjacent_topics = _adjacent_topics(payload)
    primary_topic = intake.get("primary_topic") or (payload.get("stable_topic_routing") or {}).get("primary_topic")
    primary_bundle_id = intake.get("primary_bundle_id") or (payload.get("stable_topic_routing") or {}).get("primary_bundle_id")

    return {
        "status": new_status,
        "triage_score": payload.get("overall_confidence"),
        "triage_decision": triage_decision,
        "triage_reasons": _json_dump(reasons),
        "topic_score": payload.get("overall_confidence"),
        "topic_decision": topic_decision,
        "topic_stage": "atlas_shared_pre_extraction",
        "topic_category": primary_topic,
        "atlas_constitution_version": bank.version,
        "atlas_constitution_source": bank.source_path,
        "atlas_article_type": article_type.get("value"),
        "atlas_article_type_confidence": article_type.get("confidence"),
        "atlas_article_type_source": article_type.get("source"),
        "atlas_evidence_stage": payload.get("evidence_stage"),
        "atlas_overall_confidence": payload.get("overall_confidence"),
        "atlas_intake_decision": intake.get("intake_decision"),
        "atlas_routing_target": intake.get("routing_target"),
        "atlas_domain_relevance": intake.get("domain_relevance"),
        "atlas_primary_topic": primary_topic,
        "atlas_primary_bundle_id": primary_bundle_id,
        "atlas_topic_candidates": _json_dump(candidate_topics),
        "atlas_matched_question_ids": _json_dump(matched_question_ids),
        "atlas_edge_case_kind": intake.get("edge_case_kind"),
        "atlas_novelty_signal": intake.get("novelty_signal"),
        "atlas_topic_expansion_candidate": 1 if intake.get("topic_expansion_candidate") else 0,
        "atlas_new_topic_candidate": 1 if intake.get("new_topic_candidate") else 0,
        "atlas_proposed_topic_label": intake.get("proposed_topic_label"),
        "atlas_adjacent_topics": _json_dump(adjacent_topics),
        "atlas_analysis_steps_run": _json_dump(payload.get("analysis_steps_run") or []),
        "atlas_next_action": payload.get("next_action"),
        "atlas_needs_more_evidence": 1 if payload.get("needs_more_evidence") else 0,
        "atlas_classification_payload_json": _json_dump(payload),
        "atlas_classified_at": classified_at,
        "updated_at": classified_at,
    }


def apply_update(conn: sqlite3.Connection, paper_id: str, fields: dict[str, Any]) -> None:
    assignments = ", ".join(f"{key} = ?" for key in fields)
    values = list(fields.values()) + [paper_id]
    conn.execute(f"UPDATE papers SET {assignments} WHERE paper_id = ?", values)


def fetch_backlog_rows(
    conn: sqlite3.Connection,
    *,
    limit: int,
    require_abstract: bool,
    only_pending: bool,
    unclassified_only: bool,
) -> list[sqlite3.Row]:
    clauses = ["1=1"]
    params: list[Any] = []
    if only_pending:
        clauses.append("triage_decision = 'pending'")
    if unclassified_only:
        clauses.append("(atlas_classified_at IS NULL OR TRIM(atlas_classified_at) = '')")
    if require_abstract:
        clauses.append("abstract IS NOT NULL AND TRIM(abstract) != ''")
    query = f"""
        SELECT *
        FROM papers
        WHERE {' AND '.join(clauses)}
        ORDER BY updated_at ASC, created_at ASC
        LIMIT ?
    """
    params.append(limit)
    return list(conn.execute(query, params).fetchall())


def run_backlog(
    *,
    db_path: Path,
    limit: int,
    require_abstract: bool,
    only_pending: bool,
    unclassified_only: bool,
    allow_surface_creation: bool,
    report_dir: Path,
) -> dict[str, Any]:
    db = Database(db_path)
    bank = load_topic_constitution_bank()
    subsystem = AdaptiveClassifierSubsystem(bank.constitutions)
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report_jsonl = report_dir / f"classification_run_{stamp}.jsonl"

    stats = {
        "selected": 0,
        "classified": 0,
        "send_to_eater": 0,
        "review": 0,
        "reject": 0,
        "pending": 0,
        "topic_on": 0,
        "topic_possible": 0,
        "topic_off": 0,
        "needs_abstract": 0,
        "errors": 0,
        "report_jsonl": str(report_jsonl),
        "constitution_version": bank.version,
        "constitution_source": bank.source_path,
    }

    with db.connection() as conn, report_jsonl.open("w", encoding="utf-8") as handle:
        rows = fetch_backlog_rows(
            conn,
            limit=limit,
            require_abstract=require_abstract,
            only_pending=only_pending,
            unclassified_only=unclassified_only,
        )
        stats["selected"] = len(rows)
        for row in rows:
            paper = dict(row)
            try:
                result = subsystem.classify(
                    ClassificationEvidence.from_mapping(paper),
                    allow_surface_creation=allow_surface_creation,
                )
                payload = result.to_dict()
                classified_at = utc_now_iso()
                update_fields = build_update_fields(paper, payload, bank=bank, classified_at=classified_at)
                apply_update(conn, paper["paper_id"], update_fields)
                triage_decision = update_fields["triage_decision"]
                topic_decision = update_fields["topic_decision"]
                stats["classified"] += 1
                stats[triage_decision] += 1
                if topic_decision == "on_topic":
                    stats["topic_on"] += 1
                elif topic_decision == "off_topic":
                    stats["topic_off"] += 1
                elif topic_decision == "needs_abstract":
                    stats["needs_abstract"] += 1
                else:
                    stats["topic_possible"] += 1

                handle.write(
                    json.dumps(
                        {
                            "paper_id": paper["paper_id"],
                            "title": paper.get("title"),
                            "triage_decision": triage_decision,
                            "topic_decision": topic_decision,
                            "atlas_primary_topic": update_fields["atlas_primary_topic"],
                            "atlas_article_type": update_fields["atlas_article_type"],
                            "atlas_overall_confidence": update_fields["atlas_overall_confidence"],
                            "atlas_next_action": update_fields["atlas_next_action"],
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
            except Exception as exc:
                stats["errors"] += 1
                handle.write(
                    json.dumps(
                        {
                            "paper_id": paper.get("paper_id"),
                            "title": paper.get("title"),
                            "error": str(exc),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
    summary_path = report_dir / "latest_summary.json"
    summary_path.write_text(json.dumps(stats, indent=2), encoding="utf-8")
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Atlas Shared backlog classification over AF papers.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--allow-surface-creation", action="store_true")
    parser.add_argument("--no-require-abstract", action="store_true")
    parser.add_argument("--include-non-pending", action="store_true")
    parser.add_argument("--include-already-classified", action="store_true")
    args = parser.parse_args()

    stats = run_backlog(
        db_path=args.db,
        limit=args.limit,
        require_abstract=not args.no_require_abstract,
        only_pending=not args.include_non_pending,
        unclassified_only=not args.include_already_classified,
        allow_surface_creation=args.allow_surface_creation,
        report_dir=args.report_dir,
    )
    print(json.dumps({"status": "ok", "summary": stats}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
