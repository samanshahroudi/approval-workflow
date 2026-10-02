import sqlite3

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


def test_rejected_risk_review_leaves_no_durable_proposal(tmp_path):
    from approval_workflow.workflow import RiskReview

    service = Workflow(str(tmp_path / "approval.db"))
    action = Action(kind="close_incident", incident_id=1, reason="Close before recovery confirmed")
    review = RiskReview(safe_to_propose=False, rationale="Recovery has not been confirmed")
    with pytest.raises(ValueError, match="review rejected proposal"):
        service.propose(action, review=review)
    # A rejected model review must not create a job a human could later approve.
    with sqlite3.connect(service.path) as db:
        for table in ("jobs", "audit", "incident_actions"):
            assert db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_failed_decision_audit_rolls_back_and_can_be_retried(tmp_path):
    service = Workflow(str(tmp_path / "approval.db"))
    action = Action(kind="add_note", incident_id=7, reason="Recovery confirmed")
    job = service.propose(action)
    before = service.get(job)
    with sqlite3.connect(service.path) as db:
        db.execute("CREATE TRIGGER fail_decision_audit BEFORE INSERT ON audit "
                   "WHEN NEW.event='completed' "
                   "BEGIN SELECT RAISE(ABORT, 'audit unavailable'); END")
    with pytest.raises(sqlite3.IntegrityError, match="audit unavailable"):
        service.decide(job, True, "reviewer")
    assert service.get(job) == before
    with sqlite3.connect(service.path) as db:
        assert db.execute("SELECT COUNT(*) FROM incident_actions").fetchone()[0] == 0
        assert db.execute("SELECT event,actor FROM audit").fetchall() == [("proposed", "planner")]
        db.execute("DROP TRIGGER fail_decision_audit")
    service.decide(job, True, "reviewer")
    assert service.get(job)["status"] == "completed"
    with sqlite3.connect(service.path) as db:
        assert db.execute("SELECT job_id,incident_id,kind,reason FROM incident_actions").fetchall() == [
            (job, action.incident_id, action.kind, action.reason)]
        assert db.execute("SELECT event,actor FROM audit").fetchall() == [
            ("proposed", "planner"), ("completed", "reviewer")]
