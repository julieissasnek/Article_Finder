from __future__ import annotations

from pathlib import Path

from search.discovery_orchestrator import DiscoveryOrchestrator, DiscoveryRun


class _DummyDB:
    def __init__(self, paper: dict[str, object]):
        self.paper = paper

    def get_papers_by_status(self, status: str, limit: int = 1000):
        assert status == "send_to_eater"
        return [self.paper]


class _StubBatchBundleBuilder:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.calls: list[tuple[dict[str, object], Path]] = []

    def add_paper(self, paper_record, pdf_path: Path, **kwargs):
        self.calls.append((paper_record, pdf_path))
        return self.output_dir / f"{paper_record['paper_id']}.bundle"


def test_discovery_job_phase_uses_batch_bundle_builder(monkeypatch, tmp_path: Path) -> None:
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    paper = {"paper_id": "p1", "pdf_path": str(pdf_path)}
    db = _DummyDB(paper)
    orchestrator = DiscoveryOrchestrator(db, email="test@example.com", job_output_directory=tmp_path / "jobs")
    orchestrator.current_run = DiscoveryRun(run_id="run1", started_at="2026-05-10T00:00:00")

    stub_builder = _StubBatchBundleBuilder(orchestrator.job_dir)

    def _factory(output_dir: Path):
        assert output_dir == orchestrator.job_dir
        return stub_builder

    monkeypatch.setattr("eater_interface.handoff_contract.BatchBundleBuilder", _factory)

    orchestrator._run_job_creation_phase()

    assert stub_builder.calls == [(paper, pdf_path)]
    assert orchestrator.current_run.total_jobs_created == 1
    assert orchestrator.current_run.phases[-1].items_processed == 1
    assert orchestrator.current_run.phases[-1].items_succeeded == 1
