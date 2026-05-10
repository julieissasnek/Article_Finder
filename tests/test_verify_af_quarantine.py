from pathlib import Path

from scripts.verify_af_quarantine import gather_quarantine_metrics


def test_quarantine_metrics_detect_manifest(tmp_path: Path) -> None:
    root = tmp_path / "quarantine"
    batch = root / "20260510T000000Z"
    batch.mkdir(parents=True)
    (batch / "a.pdf").write_bytes(b"%PDF-1.4\n")
    (batch / "manifest.json").write_text("{}", encoding="utf-8")

    metrics = gather_quarantine_metrics(root)
    assert metrics["latest_batch_exists"] is True
    assert metrics["latest_batch_manifest_exists"] is True
    assert metrics["latest_batch_file_count"] == 1
