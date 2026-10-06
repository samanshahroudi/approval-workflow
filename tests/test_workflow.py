import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from approval_workflow.workflow import Action, RiskReview, Workflow


@pytest.mark.parametrize("flag", ["true", "false", "yes", 0, 1])
@pytest.mark.filterwarnings("ignore:Pydantic serializer warnings:UserWarning")
def test_risk_review_rejects_coerced_flags_without_creating_proposal(tmp_path, flag):
    service = Workflow(str(tmp_path / "approval.db"))
    action = Action(kind="add_note", incident_id=7, reason="Recovery confirmed")
    with pytest.raises(ValueError):
        RiskReview(safe_to_propose=flag, rationale="Recovery confirmed")
    review = RiskReview(safe_to_propose=True, rationale="Recovery confirmed")
    with pytest.raises(ValueError):
        service.propose(action, review=review.model_copy(update={"safe_to_propose": flag}))
    with sqlite3.connect(service.path) as db:
        assert db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM audit").fetchone()[0] == 0


@pytest.mark.parametrize("safe_to_propose", [False, True])
@pytest.mark.parametrize("rationale", [" " * 5, " \t\n  "])
def test_risk_review_requires_nonblank_rationale(safe_to_propose, rationale):
    with pytest.raises(ValueError, match="rationale cannot be blank"):
        RiskReview(safe_to_propose=safe_to_propose, rationale=rationale)


def test_risk_review_preserves_meaningful_rationale():
    review = RiskReview(safe_to_propose=True, rationale="  Recovery confirmed  ")
    assert review.rationale == "  Recovery confirmed  "


def test_approval_is_single_use(tmp_path):
    service = Workflow(str(tmp_path / "approval.db"))
    job = service.propose(Action(kind="add_note", incident_id=1, reason="Customer confirmed recovery"))
    assert service.get(job)["status"] == "pending"
    service.decide(job, True, "reviewer@example.test")
    assert service.get(job)["status"] == "completed"
    with pytest.raises(ValueError):
        service.decide(job, True, "reviewer@example.test")


def test_concurrent_decisions_execute_and_audit_once(tmp_path):
    service = Workflow(str(tmp_path / "approval.db"))
    action = Action(kind="add_note", incident_id=7, reason="Recovery confirmed")
    job = service.propose(action)
    ready = Barrier(2)

    def decide(actor):
        ready.wait(timeout=5)
        try:
            service.decide(job, True, actor)
            return actor
        except ValueError as exc:
            assert str(exc) == "job already decided"
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(decide, actor) for actor in ("reviewer-one", "reviewer-two")]
        winners = [actor for future in futures if (actor := future.result(timeout=15)) is not None]
    assert len(winners) == 1
    assert service.get(job)["status"] == "completed"
    with sqlite3.connect(service.path) as db:
        assert db.execute("SELECT job_id,incident_id,kind,reason FROM incident_actions").fetchall() == [
            (job, action.incident_id, action.kind, action.reason)]
        assert db.execute("SELECT event,actor FROM audit ORDER BY rowid").fetchall() == [
            ("proposed", "planner"), ("completed", winners[0])]


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


@pytest.mark.parametrize("decision", ["false", "true", 0, 1, None, [], {}])
def test_decision_requires_boolean_without_changing_job(tmp_path, decision):
    service = Workflow(str(tmp_path / "approval.db"))
    job = service.propose(Action(kind="add_note", incident_id=7, reason="Recovery confirmed"))
    before = service.get(job)
    with pytest.raises(TypeError, match="decision must be a boolean"):
        service.decide(job, decision, "reviewer")
    assert service.get(job) == before
    with sqlite3.connect(service.path) as db:
        assert db.execute("SELECT COUNT(*) FROM incident_actions").fetchone()[0] == 0
        assert db.execute("SELECT event FROM audit").fetchall() == [("proposed",)]
    service.decide(job, False, "reviewer")
    assert service.get(job)["status"] == "rejected"


@pytest.mark.parametrize("field,value", [("incident_id", 0), ("kind", "delete_incident"),
                                       ("reason", "     ")])
def test_invalid_copied_action_cannot_create_proposal(tmp_path, field, value):
    service = Workflow(str(tmp_path / "approval.db"))
    action = Action(kind="add_note", incident_id=7, reason="Recovery confirmed")
    with pytest.raises(ValueError):
        service.propose(action.model_copy(update={field: value}))
    with sqlite3.connect(service.path) as db:
        assert db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM audit").fetchone()[0] == 0
    job = service.propose(action)
    service.decide(job, True, "reviewer")
    assert service.get(job)["status"] == "completed"


def test_invalid_copied_review_cannot_create_proposal(tmp_path):
    service = Workflow(str(tmp_path / "approval.db"))
    action = Action(kind="add_note", incident_id=7, reason="Recovery confirmed")
    review = RiskReview(safe_to_propose=True, rationale="Recovery has been confirmed")
    with pytest.raises(ValueError, match="rationale cannot be blank"):
        service.propose(action, review=review.model_copy(update={"rationale": "     "}))
    with sqlite3.connect(service.path) as db:
        assert db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM audit").fetchone()[0] == 0
    assert service.get(service.propose(action, review=review))["status"] == "pending"


def test_connections_close_after_proposal_reads_and_decisions(tmp_path, monkeypatch):
    connections = []
    connect = sqlite3.connect

    def track_connection(*args, **kwargs):
        connection = connect(*args, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", track_connection)
    workflow = Workflow(str(tmp_path / "approval.db"))
    action = Action(kind="add_note", incident_id=7, reason="Recovery confirmed")
    job = workflow.propose(action)
    assert workflow.get(job)["status"] == "pending"
    workflow.decide(job, True, "reviewer")
    assert workflow.get(job)["status"] == "completed"
    with pytest.raises(ValueError, match="already decided"):
        workflow.decide(job, True, "reviewer")
    rejected = workflow.propose(action)
    workflow.decide(rejected, False, "reviewer")
    with pytest.raises(KeyError):
        workflow.get("missing")
    assert connections
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
            connection.execute("SELECT 1")


@pytest.mark.parametrize("incident_id", [True, False, "7", 7.0, 7.5])
@pytest.mark.filterwarnings("ignore:Pydantic serializer warnings:UserWarning")
def test_incident_ids_cannot_be_coerced_into_proposals(tmp_path, incident_id):
    service = Workflow(str(tmp_path / "approval.db"))
    with pytest.raises(ValueError):
        Action(kind="add_note", incident_id=incident_id, reason="Recovery confirmed")
    action = Action(kind="add_note", incident_id=7, reason="Recovery confirmed")
    with pytest.raises(ValueError):
        service.propose(action.model_copy(update={"incident_id": incident_id}))
    with sqlite3.connect(service.path) as db:
        assert db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM audit").fetchone()[0] == 0
    assert service.get(service.propose(action))["action"]["incident_id"] == 7
