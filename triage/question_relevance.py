from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
ATLAS_SHARED_SRC = REPO_ROOT.parent / "atlas_shared" / "src"
if str(ATLAS_SHARED_SRC) not in sys.path:
    sys.path.insert(0, str(ATLAS_SHARED_SRC))

from atlas_shared.classifier_system import (  # type: ignore[import-not-found]
    AdaptiveClassifierSubsystem,
    ClassificationEvidence,
)
from atlas_shared.relevance import (  # type: ignore[import-not-found]
    QuestionConstitution,
    RelevanceAssessment,
    SupportsRelevanceAdjudication,
)
from atlas_shared.registry_sink import SupportsClassificationRegistry  # type: ignore[import-not-found]
from atlas_shared.cli_adjudicator import (  # type: ignore[import-not-found]
    AGCommandAdjudicator,
    ClaudeCLIAdjudicator,
    CodexCLIAdjudicator,
)

class ConstitutionBank:
    """Load and filter panel-authored question constitutions."""

    def __init__(self, constitutions: Sequence[QuestionConstitution]) -> None:
        self.constitutions = tuple(constitutions)

    @classmethod
    def from_json(
        cls,
        path: Path,
        *,
        active_question_ids: Sequence[str] = (),
    ) -> "ConstitutionBank":
        data = json.loads(path.read_text())
        if isinstance(data, dict) and "questions" in data:
            raw_questions = data["questions"]
        elif isinstance(data, list):
            raw_questions = data
        else:
            raise ValueError("Constitution bank must be a list or an object with a 'questions' key")

        allowed = {str(item) for item in active_question_ids if str(item).strip()}
        constitutions: list[QuestionConstitution] = []
        for item in raw_questions:
            constitution = QuestionConstitution.from_panel_spec(item)
            if allowed and constitution.question_id not in allowed:
                continue
            constitutions.append(constitution)
        return cls(constitutions)


def build_question_adjudicator(
    kind: str,
    *,
    command: Sequence[str] = (),
    cwd: Path | None = None,
    timeout_seconds: int = 180,
):
    normalized = (kind or "none").strip().lower()
    if normalized in {"", "none", "off", "disabled"}:
        return None
    if normalized == "ag":
        if not command:
            raise ValueError("AG adjudicator requires a command sequence")
        return AGCommandAdjudicator(command, cwd=cwd, timeout_seconds=timeout_seconds)
    if normalized == "codex":
        return CodexCLIAdjudicator(cwd=cwd, timeout_seconds=timeout_seconds)
    if normalized == "claude":
        return ClaudeCLIAdjudicator(cwd=cwd, timeout_seconds=timeout_seconds)
    raise ValueError(f"Unknown question adjudicator kind: {kind}")


class QuestionAwareTriageGate:
    """
    Apply one or more question constitutions at AF intake.

    This is intentionally a second opinion over the existing taxonomy triage,
    not a replacement for it.
    """

    def __init__(
        self,
        constitution_bank: ConstitutionBank,
        *,
        adjudicator: SupportsRelevanceAdjudication | None = None,
        registry_sink: SupportsClassificationRegistry | None = None,
        adjudication_policy: str = "borderline_only",
    ) -> None:
        self.bank = constitution_bank
        self.registry_sink = registry_sink
        self.subsystem = AdaptiveClassifierSubsystem(
            constitutions=self.bank.constitutions,
            adjudicator=adjudicator,
            registry_sink=registry_sink,
            adjudication_policy=adjudication_policy,
        )

    @classmethod
    def from_json(
        cls,
        path: Path,
        *,
        active_question_ids: Sequence[str] = (),
        adjudicator: SupportsRelevanceAdjudication | None = None,
        registry_sink: SupportsClassificationRegistry | None = None,
        adjudication_policy: str = "borderline_only",
    ) -> "QuestionAwareTriageGate":
        bank = ConstitutionBank.from_json(path, active_question_ids=active_question_ids)
        return cls(
            bank,
            adjudicator=adjudicator,
            registry_sink=registry_sink,
            adjudication_policy=adjudication_policy,
        )

    def assess_paper(self, paper: Mapping[str, Any]) -> dict[str, Any]:
        if not self.bank.constitutions:
            return {
                "enabled": False,
                "questions_considered": 0,
                "best_verdict": None,
                "recommended_decision": None,
                "reasons": [],
                "assessments": [],
            }

        evidence = ClassificationEvidence.from_mapping(paper)
        result = self.subsystem.classify(evidence)
        if result.surface_snapshot is not None:
            evidence = evidence.with_surface_snapshot(result.surface_snapshot)
        article = evidence.to_article_candidate()
        assessments = tuple(result.stable_topic_routing.all_assessments) if result.stable_topic_routing else ()
        question_summary = result.question_summary

        if question_summary.best_verdict == "accept":
            recommended_decision = "send_to_eater"
        elif question_summary.best_verdict == "edge_case":
            recommended_decision = "review"
        else:
            recommended_decision = "reject"

        summary = {
            "enabled": question_summary.enabled,
            "questions_considered": question_summary.questions_considered,
            "best_question_id": question_summary.best_question_id,
            "best_bundle_id": question_summary.best_bundle_id,
            "best_verdict": question_summary.best_verdict,
            "best_confidence": question_summary.best_confidence,
            "recommended_decision": recommended_decision,
            "needs_manual_review": question_summary.needs_manual_review,
            "best_edge_case_kind": question_summary.best_edge_case_kind,
            "max_novelty_signal": question_summary.max_novelty_signal,
            "topic_expansion_candidate_count": question_summary.topic_expansion_candidate_count,
            "new_topic_candidate_count": question_summary.new_topic_candidate_count,
            "proposed_topic_labels": list(question_summary.proposed_topic_labels),
            "accepted_question_ids": list(question_summary.accepted_question_ids),
            "edge_case_question_ids": list(question_summary.edge_case_question_ids),
            "rejected_question_ids": list(question_summary.rejected_question_ids),
            "reasons": list(question_summary.reasons),
            "assessments": [self._assessment_to_dict(item) for item in assessments],
            "evidence_stage": result.evidence_stage,
            "analysis_steps_run": list(result.analysis_steps_run),
            "next_action": result.next_action,
            "needs_more_evidence": result.needs_more_evidence,
            "overall_confidence": result.overall_confidence,
            "primary_topic_candidate": (
                result.stable_topic_routing.primary_topic if result.stable_topic_routing else None
            ),
        }
        if self.registry_sink is not None:
            self.registry_sink.record_question_summary(article, summary)
            if result.stable_topic_routing is not None:
                self.registry_sink.record_bundle_routing(article, result.stable_topic_routing)
        return summary

    @staticmethod
    def merge_decision(existing_decision: str, summary: Mapping[str, Any]) -> str:
        if not summary.get("enabled"):
            return existing_decision

        recommendation = str(summary.get("recommended_decision") or "")
        if recommendation == "send_to_eater":
            return "send_to_eater"
        if recommendation == "review" and existing_decision == "reject":
            return "review"
        return existing_decision

    @staticmethod
    def _assessment_to_dict(item: RelevanceAssessment) -> dict[str, Any]:
        return {
            "paper_id": item.paper_id,
            "question_id": item.question_id,
            "bundle_id": item.bundle_id,
            "verdict": item.verdict,
            "confidence": item.confidence,
            "needs_manual_review": item.needs_manual_review,
            "article_type": item.article_type.value,
            "adjudication_source": item.adjudication_source,
            "edge_case_kind": item.edge_case_kind,
            "novelty_signal": item.novelty_signal,
            "topic_expansion_candidate": item.topic_expansion_candidate,
            "new_topic_candidate": item.new_topic_candidate,
            "proposed_topic_label": item.proposed_topic_label,
            "adjacent_topics": list(item.adjacent_topics),
            "reasons": list(item.reasons),
            "environment_hits": list(item.environment_hits),
            "outcome_hits": list(item.outcome_hits),
            "exclusion_hits": list(item.exclusion_hits),
            "edge_hits": list(item.edge_hits),
            "evidence_hits": list(item.evidence_hits),
        }
