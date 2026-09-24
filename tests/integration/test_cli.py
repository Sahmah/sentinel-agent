from sentinel_agent.cli import main


def test_demo_runs_end_to_end(capsys, monkeypatch):
    monkeypatch.delenv("SENTINEL_LLM_BACKEND", raising=False)
    assert main(["demo", "--calibration-scenes", "2"]) == 0
    out = capsys.readouterr().out
    assert "alert  (real)" in out
    assert "Calibration, out of sample" in out


def test_webcam_reports_unopenable_source(capsys, tmp_path):
    missing = tmp_path / "nope.mp4"
    assert main(["webcam", "--source", str(missing), "--no-window"]) == 1
    assert "Could not open" in capsys.readouterr().err
