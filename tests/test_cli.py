import pytest

from approval_workflow.cli import main


@pytest.mark.parametrize("flags", [[], ["--approve", "--reject"]])
def test_invalid_decision_flags_do_not_create_database(tmp_path, monkeypatch, capsys, flags):
    path = tmp_path / "approval.db"
    monkeypatch.setattr("sys.argv", ["approval", "--db", str(path), "decide", "job-id",
                                    "--actor", "reviewer", *flags])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    assert "error:" in capsys.readouterr().err
    assert not path.exists()


@pytest.mark.parametrize("flag,status", [("--approve", "completed"), ("--reject", "rejected")])
def test_valid_decision_flags_route_to_workflow(tmp_path, monkeypatch, flag, status):
    from approval_workflow.workflow import Action, Workflow

    path = tmp_path / "approval.db"
    workflow = Workflow(str(path))
    job = workflow.propose(Action(kind="add_note", incident_id=7, reason="Recovery confirmed"))
    monkeypatch.setattr("sys.argv", ["approval", "--db", str(path), "decide", job,
                                    "--actor", "reviewer", flag])
    main()
    assert workflow.get(job)["status"] == status
