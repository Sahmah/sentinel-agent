from sentinel_agent.cli import main


def test_demo_runs_end_to_end(capsys, monkeypatch):
    monkeypatch.delenv("SENTINEL_LLM_BACKEND", raising=False)
    assert main(["demo", "--calibration-scenes", "2"]) == 0
    out = capsys.readouterr().out
    assert "alert  (real)" in out
    assert "Calibration, out of sample" in out
    assert "Saved 10 events" in out


def test_demo_stores_what_it_printed(capsys):
    from sentinel_agent.storage import build_storage
    from sentinel_agent.storage.base import EventFilter

    main(["demo", "--calibration-scenes", "2"])
    page = build_storage().query(EventFilter(action="alert"), limit=10)
    (alert,) = page.events
    assert (alert.source, alert.label, alert.is_true_positive) == ("demo", "person", True)
    assert alert.p_cv_calibrated and alert.llm_confidence == 0.9

    main(["demo", "--calibration-scenes", "2", "--no-store"])
    assert "Saved" not in capsys.readouterr().out.split("Calibration, out of sample")[-1]
    assert len(build_storage().query(EventFilter(), limit=100).events) == 10


def test_webcam_reports_unopenable_source(capsys, tmp_path):
    missing = tmp_path / "nope.mp4"
    assert main(["webcam", "--source", str(missing), "--no-window"]) == 1
    assert "Could not open" in capsys.readouterr().err
