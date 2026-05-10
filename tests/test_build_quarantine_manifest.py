import json
from pathlib import Path

from core.quarantine import build_manifest, write_manifest


def test_build_manifest_records_file_count_and_bytes(tmp_path: Path) -> None:
    batch = tmp_path / "20260510T000000Z"
    batch.mkdir()
    (batch / "a.pdf").write_bytes(b"abc")
    (batch / "b.pdf").write_bytes(b"defg")

    manifest = build_manifest(batch)
    assert manifest["file_count"] == 2
    assert manifest["total_bytes"] == 7

    manifest_path = write_manifest(batch, manifest)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["file_count"] == 2
