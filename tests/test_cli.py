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


@pytest.mark.parametrize("use_model", [False, True])
def test_valid_proposal_modes(tmp_path, monkeypatch, capsys, use_model):
    from approval_workflow.workflow import Action, RiskReview, Workflow

    action = Action(kind="add_note", incident_id=7, reason="Recovery confirmed")
    calls = []

    def plan(request):
        calls.append(request)
        return action

    def review(proposed):
        assert proposed == action
        calls.append("reviewed")
        return RiskReview(safe_to_propose=True, rationale="Recovery is confirmed")

    monkeypatch.setattr("approval_workflow.cli.plan_live", plan)
    monkeypatch.setattr("approval_workflow.cli.review_live", review)
    path = tmp_path / "approval.db"
    flags = (["--request", "Add a recovery note"] if use_model else
             ["--kind", "add_note", "--incident-id", "7", "--reason", action.reason])
    monkeypatch.setattr("sys.argv", ["approval", "--db", str(path), "propose", *flags])
    main()
    job_id = capsys.readouterr().out.strip()
    job = Workflow(str(path)).get(job_id)
    assert job["status"] == "pending"
    assert job["action"] == action.model_dump()
    assert calls == (["Add a recovery note", "reviewed"] if use_model else [])


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


@pytest.mark.parametrize("flags", [
    [],
    ["--kind", "add_note", "--incident-id", "7"],
    ["--kind", "add_note", "--reason", "Recovery confirmed"],
    ["--incident-id", "7", "--reason", "Recovery confirmed"],
    ["--request", "   "],
    ["--request", "Add a note", "--kind", "close_incident"],
    ["--request", "Add a note", "--incident-id", "7"],
    ["--request", "Add a note", "--reason", "Recovery confirmed"],
])
def test_invalid_proposal_arguments_have_no_side_effects(tmp_path, monkeypatch, capsys, flags):
    def unexpected_call(*args):
        pytest.fail("invalid arguments must not call the model")

    monkeypatch.setattr("approval_workflow.cli.plan_live", unexpected_call)
    monkeypatch.setattr("approval_workflow.cli.review_live", unexpected_call)
    path = tmp_path / "approval.db"
    monkeypatch.setattr("sys.argv", ["approval", "--db", str(path), "propose", *flags])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    assert "error:" in capsys.readouterr().err
    assert not path.exists()


@pytest.mark.parametrize("actor", ["", "   ", "\t\n"])
@pytest.mark.parametrize("flag", ["--approve", "--reject"])
def test_blank_decision_actor_does_not_create_database(tmp_path, monkeypatch, capsys, actor, flag):
    path = tmp_path / "approval.db"
    monkeypatch.setattr("sys.argv", ["approval", "--db", str(path), "decide", "job-id",
                                    "--actor", actor, flag])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    assert "--actor cannot be blank" in capsys.readouterr().err
    assert not path.exists()
