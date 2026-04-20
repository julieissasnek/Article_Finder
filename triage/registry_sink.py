from __future__ import annotations
from pathlib import Path
import sys
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
ATLAS_SHARED_SRC = REPO_ROOT.parent / "atlas_shared" / "src"
AE_REPO_ROOT = REPO_ROOT.parent / "Article_Eater_PostQuinean_v1_recovery"
if str(ATLAS_SHARED_SRC) not in sys.path:
    sys.path.insert(0, str(ATLAS_SHARED_SRC))
if str(AE_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(AE_REPO_ROOT))

from atlas_shared.registry_sink import SupportsClassificationRegistry  # type: ignore[import-not-found]


def _source_type_from_adjudication_source(source: str) -> str:
    normalized = str(source or "").strip().lower()
    if not normalized or normalized in {"heuristic_filter", "article_record", "heuristic_classifier"}:
        return "heuristic"
    if normalized.startswith("ag") or "ag::" in normalized:
        return "ag_adjudication"
    if "codex" in normalized:
        return "codex_adjudication"
    if "claude" in normalized or "llm" in normalized or "panel" in normalized:
        return "llm"
    return "heuristic"


class AEUnifiedRegistrySink(SupportsClassificationRegistry):
    """
    Adapter from atlas_shared semantic notifications to AE's unified registry writer.

    The shared package remains unaware of AE internals. AF can provide this sink
    when it wants shared classifiers to emit registry updates.
    """

    def __init__(
        self,
        *,
        registry_db: Path | None = None,
        lifecycle_db: Path | None = None,
        dry_run: bool = False,
    ) -> None:
        self.registry_db = registry_db
        self.lifecycle_db = lifecycle_db
        self.dry_run = dry_run

    def _notify(
        self,
        *,
        paper_id: str,
        fields: Mapping[str, Any],
        source_subsystem: str,
        source_type: str,
        broker_string: str | None = None,
        event_stage: str = "typed",
        details_json: Mapping[str, Any] | None = None,
        classification_fact: Mapping[str, Any] | None = None,
    ) -> Any:
        from src.services.notify_registry import notify_registry  # type: ignore[import-not-found]

        return notify_registry(
            paper_id=paper_id,
            fields=dict(fields),
            source_subsystem=source_subsystem,
            source_type=source_type,
            broker_string=broker_string,
            event_stage=event_stage,
            details_json=dict(details_json or {}),
            classification_fact=dict(classification_fact or {}) if classification_fact else None,
            registry_db=self.registry_db,
            lifecycle_db=self.lifecycle_db,
            dry_run=self.dry_run,
        )

    def record_article_type(self, article, decision) -> Any:
        source_type = "manual" if decision.source == "article_record" else "heuristic"
        return self._notify(
            paper_id=article.paper_id,
            fields={
                "article_type_current": decision.value,
                "article_type_confidence": decision.confidence,
            },
            source_subsystem="atlas_shared.article_types.HeuristicArticleTypeClassifier",
            source_type=source_type,
            details_json={
                "article_type_evidence": list(decision.evidence),
                "article_type_source": decision.source,
            },
            classification_fact={
                "dimension": "article_type",
                "label": decision.value,
                "confidence": decision.confidence,
                "details_json": {
                    "evidence": list(decision.evidence),
                    "source": decision.source,
                },
            },
        )

    def record_question_assessment(self, article, constitution, assessment) -> Any:
        return self._notify(
            paper_id=article.paper_id,
            fields={},
            source_subsystem="atlas_shared.relevance.QuestionArticleRelevanceFilter",
            source_type=_source_type_from_adjudication_source(assessment.adjudication_source),
            broker_string=None if assessment.adjudication_source == "heuristic_filter" else assessment.adjudication_source,
            details_json={
                "question_id": constitution.question_id,
                "bundle_id": assessment.bundle_id,
                "verdict": assessment.verdict,
                "confidence": assessment.confidence,
                "reasons": list(assessment.reasons),
                "article_type": assessment.article_type.value,
                "environment_hits": list(assessment.environment_hits),
                "outcome_hits": list(assessment.outcome_hits),
                "exclusion_hits": list(assessment.exclusion_hits),
                "edge_hits": list(assessment.edge_hits),
                "evidence_hits": list(assessment.evidence_hits),
                "edge_case_kind": assessment.edge_case_kind,
                "novelty_signal": assessment.novelty_signal,
                "topic_expansion_candidate": assessment.topic_expansion_candidate,
                "new_topic_candidate": assessment.new_topic_candidate,
                "proposed_topic_label": assessment.proposed_topic_label,
                "adjacent_topics": list(assessment.adjacent_topics),
            },
            classification_fact={
                "dimension": "question_relevance",
                "label": assessment.verdict,
                "confidence": assessment.confidence,
                "question_id": constitution.question_id,
                "bundle_id": assessment.bundle_id,
                "topic_label": constitution.topic,
                "edge_case_kind": assessment.edge_case_kind,
                "novelty_signal": assessment.novelty_signal,
                "details_json": {
                    "article_type": assessment.article_type.value,
                    "reasons": list(assessment.reasons),
                    "environment_hits": list(assessment.environment_hits),
                    "outcome_hits": list(assessment.outcome_hits),
                    "exclusion_hits": list(assessment.exclusion_hits),
                    "edge_hits": list(assessment.edge_hits),
                    "evidence_hits": list(assessment.evidence_hits),
                    "topic_expansion_candidate": assessment.topic_expansion_candidate,
                    "new_topic_candidate": assessment.new_topic_candidate,
                    "proposed_topic_label": assessment.proposed_topic_label,
                    "adjacent_topics": list(assessment.adjacent_topics),
                },
            },
        )

    def record_question_summary(self, article, summary: Mapping[str, Any]) -> Any:
        return self._notify(
            paper_id=article.paper_id,
            fields={
                "question_filter_enabled": 1 if summary.get("enabled") else 0,
                "question_best_verdict": summary.get("best_verdict"),
                "question_best_confidence": summary.get("best_confidence"),
                "question_best_question_id": summary.get("best_question_id"),
                "question_best_bundle_id": summary.get("best_bundle_id"),
                "question_best_edge_case_kind": summary.get("best_edge_case_kind"),
                "question_max_novelty_signal": summary.get("max_novelty_signal"),
            },
            source_subsystem="Article_Finder_v3_2_3.triage.question_relevance.QuestionAwareTriageGate",
            source_type="heuristic",
            details_json={
                "question_relevance_summary": dict(summary),
                "accepted_question_ids": list(summary.get("accepted_question_ids", [])),
                "edge_case_question_ids": list(summary.get("edge_case_question_ids", [])),
                "rejected_question_ids": list(summary.get("rejected_question_ids", [])),
                "proposed_topic_labels": list(summary.get("proposed_topic_labels", [])),
            },
        )

    def record_bundle_routing(self, article, routing) -> Any:
        return self._notify(
            paper_id=article.paper_id,
            fields={
                "primary_topic_candidate": routing.primary_topic,
                "primary_bundle_candidate": routing.primary_bundle_id,
                "topic_expansion_candidate_count": sum(
                    candidate.topic_expansion_signal_count for candidate in routing.candidates
                ),
                "new_topic_candidate_count": sum(
                    candidate.new_topic_signal_count for candidate in routing.candidates
                ),
            },
            source_subsystem="atlas_shared.bundle_router.QuestionBundleRouter",
            source_type="heuristic",
            details_json={
                "bundle_routing_result": {
                    "primary_topic": routing.primary_topic,
                    "primary_bundle_id": routing.primary_bundle_id,
                },
                "bundle_candidates": [
                    {
                        "topic": candidate.topic,
                        "score": candidate.score,
                        "accepted_count": candidate.accepted_count,
                        "edge_case_count": candidate.edge_case_count,
                        "topic_expansion_signal_count": candidate.topic_expansion_signal_count,
                        "new_topic_signal_count": candidate.new_topic_signal_count,
                        "max_novelty_signal": candidate.max_novelty_signal,
                        "best_question_id": candidate.best_question_id,
                        "best_bundle_id": candidate.best_bundle_id,
                        "best_verdict": candidate.best_verdict,
                        "best_confidence": candidate.best_confidence,
                        "proposed_topic_labels": list(candidate.proposed_topic_labels),
                    }
                    for candidate in routing.candidates
                ],
                "emergent_candidates": [
                    {
                        "topic": candidate.topic,
                        "score": candidate.score,
                        "proposed_topic_labels": list(candidate.proposed_topic_labels),
                        "max_novelty_signal": candidate.max_novelty_signal,
                    }
                    for candidate in routing.emergent_candidates
                ],
            },
            classification_fact={
                "dimension": "bundle_routing",
                "label": routing.primary_topic or "unresolved",
                "confidence": routing.candidates[0].best_confidence if routing.candidates else 0.0,
                "bundle_id": routing.primary_bundle_id,
                "topic_label": routing.primary_topic,
                "details_json": {
                    "candidate_topics": [candidate.topic for candidate in routing.candidates],
                    "emergent_topics": [candidate.topic for candidate in routing.emergent_candidates],
                },
            },
        )
