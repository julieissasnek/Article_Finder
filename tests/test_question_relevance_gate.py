from __future__ import annotations

import json
from pathlib import Path

from atlas_shared.relevance import AdjudicationResult
from triage.classifier import ClassificationResult, TriageFilter
from triage.question_relevance import QuestionAwareTriageGate


class _RecordingSink:
    def __init__(self) -> None:
        self.summaries = []
        self.routings = []

    def record_article_type(self, article, decision):
        return None

    def record_question_assessment(self, article, constitution, assessment):
        return None

    def record_question_summary(self, article, summary):
        self.summaries.append((article.paper_id, summary["best_verdict"], summary["best_question_id"]))

    def record_bundle_routing(self, article, routing):
        self.routings.append((article.paper_id, routing.primary_topic))


class _StubClassifier:
    def classify_paper(self, paper_id: str, title: str, abstract: str | None = None):
        return ClassificationResult(
            paper_id=paper_id,
            scores={},
            top_nodes=[],
            facet_summary={},
            domain_score=0.22,
            triage_decision="reject",
            triage_reasons=["Low domain relevance: 0.22"],
        )


class _NoveltyAdjudicator:
    def adjudicate(self, request):
        return AdjudicationResult(
            verdict="edge_case",
            confidence=0.77,
            reasons=("This edge case suggests a topic broadening toward restoration.",),
            needs_manual_review=True,
            source="stub_llm",
            edge_case_kind="topic_expansion_candidate",
            novelty_signal=0.82,
            topic_expansion_candidate=True,
            new_topic_candidate=False,
            proposed_topic_label="Nature Exposure and Restoration",
            adjacent_topics=("Nature and Attention", "Affect"),
        )


def _constitution_bank() -> dict:
    return {
        "version": "2026-04-07",
        "questions": [
            {
                "question_id": "SQ-ART-001",
                "question_text": "Does exposure to natural environments improve directed attention in adults?",
                "topic": "Nature and Attention",
                "panel_status": "llm_panel_drafted",
                "constitution_version": "v1",
                "environment_terms": ["nature", "natural environment", "green view", "forest"],
                "outcome_terms": ["directed attention", "attention"],
                "exclusion_terms": ["adhd", "attention deficit"],
                "edge_terms": ["restoration", "stress recovery"],
                "accept_indicators": ["Nature exposure plus direct attention outcome."],
                "reject_indicators": ["ADHD treatment papers and unrelated nature pieces."],
                "edge_case_indicators": ["Restoration work without direct attention evidence."],
                "required_evidence_terms": ["participants", "p <", "attention task"]
            }
        ]
    }


def test_question_gate_promotes_reject_to_send_to_eater(tmp_path: Path) -> None:
    bank_path = tmp_path / "constitutions.json"
    bank_path.write_text(json.dumps(_constitution_bank()))

    gate = QuestionAwareTriageGate.from_json(bank_path)
    triage = TriageFilter(_StubClassifier(), question_relevance_gate=gate)

    result = triage.triage_paper(
        paper_id="PDF-0001",
        title="Natural environments improve directed attention in office workers",
        abstract="We conducted an experiment with 84 participants and the attention task improved (p < .01).",
        store_results=False,
    )

    assert result.triage_decision == "send_to_eater"
    assert result.question_relevance["best_verdict"] == "accept"
    assert result.question_relevance["recommended_decision"] == "send_to_eater"


def test_question_gate_promotes_reject_to_review_for_edge_case(tmp_path: Path) -> None:
    bank_path = tmp_path / "constitutions.json"
    bank_path.write_text(json.dumps(_constitution_bank()))

    gate = QuestionAwareTriageGate.from_json(bank_path)
    triage = TriageFilter(_StubClassifier(), question_relevance_gate=gate)

    result = triage.triage_paper(
        paper_id="PDF-0002",
        title="Forest bathing reduces stress in adults",
        abstract="Participants exposed to forest bathing showed lower cortisol and better mood but no attention task was administered.",
        store_results=False,
    )

    assert result.triage_decision == "review"
    assert result.question_relevance["best_verdict"] == "edge_case"


def test_question_gate_surfaces_novelty_fields(tmp_path: Path) -> None:
    bank_path = tmp_path / "constitutions.json"
    bank_path.write_text(json.dumps(_constitution_bank()))

    gate = QuestionAwareTriageGate.from_json(bank_path, adjudicator=_NoveltyAdjudicator())
    triage = TriageFilter(_StubClassifier(), question_relevance_gate=gate)

    result = triage.triage_paper(
        paper_id="PDF-0003",
        title="Forest bathing reduces stress in adults",
        abstract="Participants exposed to forest bathing showed lower cortisol and better mood but no attention task was administered.",
        store_results=False,
    )

    assert result.question_relevance["best_edge_case_kind"] == "topic_expansion_candidate"
    assert result.question_relevance["max_novelty_signal"] == 0.82
    assert result.question_relevance["topic_expansion_candidate_count"] == 1
    assert "Nature Exposure and Restoration" in result.question_relevance["proposed_topic_labels"]


def test_question_gate_records_summary_with_sink(tmp_path: Path) -> None:
    bank_path = tmp_path / "constitutions.json"
    bank_path.write_text(json.dumps(_constitution_bank()))
    sink = _RecordingSink()

    gate = QuestionAwareTriageGate.from_json(bank_path, registry_sink=sink)
    triage = TriageFilter(_StubClassifier(), question_relevance_gate=gate)

    result = triage.triage_paper(
        paper_id="PDF-0004",
        title="Natural environments improve directed attention in office workers",
        abstract="We conducted an experiment with 84 participants and the attention task improved (p < .01).",
        store_results=False,
    )

    assert result.question_relevance["best_verdict"] == "accept"
    assert sink.summaries == [("PDF-0004", "accept", "SQ-ART-001")]
    assert sink.routings == [("PDF-0004", "Nature and Attention")]


def test_question_gate_can_use_late_extraction_fields(tmp_path: Path) -> None:
    bank_path = tmp_path / "constitutions.json"
    bank_path.write_text(json.dumps(_constitution_bank()))

    gate = QuestionAwareTriageGate.from_json(bank_path)
    triage = TriageFilter(_StubClassifier(), question_relevance_gate=gate)

    result = triage.triage_paper(
        paper_id="PDF-0005",
        title="Nature exposure and attention after office work",
        abstract="",
        extra_fields={
            "processing_stage": "post_extraction",
            "methods_surface_summary": "Experiment with participants and an attention task.",
            "independent_variables": "natural environment exposure",
            "dependent_variables": "directed attention",
            "measurement_inventory": [{"outcome": "directed attention", "measure_name": "attention task"}],
            "science_writer_summary": {
                "sections": {
                    "Core Finding": "Natural environment exposure improved directed attention with p < .05."
                }
            },
        },
        store_results=False,
    )

    assert result.triage_decision == "send_to_eater"
    assert result.question_relevance["best_verdict"] == "accept"
