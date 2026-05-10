from core.system_health import CheckResult, summarize_results


def test_summarize_results_reports_failure() -> None:
    results = [
        CheckResult(label="doctor_deep", ok=True, returncode=0, stdout="ok"),
        CheckResult(label="verify_af_quarantine", ok=False, returncode=1, stdout="bad"),
    ]
    payload = summarize_results(results)
    assert payload["status"] == "fail"
    assert payload["checks"]["doctor_deep"] == "OK"
    assert payload["checks"]["verify_af_quarantine"] == "FAILED"
