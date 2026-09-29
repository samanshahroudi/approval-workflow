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
