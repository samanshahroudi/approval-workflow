import pytest

from approval_workflow.workflow import Action, Workflow


def test_approval_is_single_use(tmp_path):
    service = Workflow(str(tmp_path / "approval.db"))
    job = service.propose(Action(kind="add_note", incident_id=1, reason="Customer confirmed recovery"))
    assert service.get(job)["status"] == "pending"
    service.decide(job, True, "reviewer@example.test")
    assert service.get(job)["status"] == "completed"
    with pytest.raises(ValueError):
        service.decide(job, True, "reviewer@example.test")


def test_proposal_requires_actor(tmp_path):
    service = Workflow(str(tmp_path / "approval.db"))
    action = Action(kind="add_note", incident_id=1, reason="Customer confirmed recovery")
    with pytest.raises(ValueError, match="proposer identity"):
        service.propose(action, actor="   ")


@pytest.mark.parametrize("reason", ["     ", " \t\n  "])
def test_action_requires_nonblank_reason(reason):
    with pytest.raises(ValueError, match="reason cannot be blank"):
        Action(kind="add_note", incident_id=1, reason=reason)


def test_action_preserves_meaningful_reason():
    action = Action(kind="add_note", incident_id=1, reason="  Customer confirmed recovery  ")
    assert action.reason == "  Customer confirmed recovery  "
