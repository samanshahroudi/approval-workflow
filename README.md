# Approval-gated incident workflow

## The problem

An agent that proposes operational actions should not silently perform them. This project separates a typed model proposal from a human decision and records the outcome in a durable SQLite job and audit log. LangGraph owns the routing from approval state to the execution node.

## Architecture and how it works

`request → planner → independent risk review → pending job → human decision → LangGraph branch → incident action record + audit`

The deterministic CLI path can propose an action without a model. The `--request` path uses one model call to produce an `Action` and a second, separately prompted call to critique it as a typed `RiskReview`. A failed review reports its rationale as a CLI usage error and prevents a pending job; a passed review still needs a human decision. `decide` takes an approver identity and either rejects or records the authorized action. A SQLite write lock makes the decision single-use. The graph is intentionally small so the control boundary is visible. Business state is stored in SQLite; LangGraph's in-memory invocation is reconstructed from that state, rather than pretending a process-local checkpoint is durable.

`Workflow.decide` requires a boolean decision; strings such as `"false"`, integers, and other values are rejected before changing the job or audit log.

## Concepts and choices

Proposals revalidate actions and risk reviews before persisting them, including objects modified through Pydantic methods that bypass validation.

Pydantic limits the action vocabulary and incident ID. LangGraph illustrates typed state, conditional routing, and a bounded terminal path. SQLite holds jobs, audit events, and approved action records. The code is in `workflow.py` and the interface in `cli.py`.

## Run and example

From this repository after `python -m pip install -e ".[dev]"`:

```bash
python -m approval_workflow.cli --db approval.db propose --kind add_note --incident-id 7 --reason 'Customer confirmed recovery'
python -m approval_workflow.cli --db approval.db show JOB_ID
python -m approval_workflow.cli --db approval.db decide JOB_ID --approve --actor reviewer@example.test
```

Substitute the printed job ID. For a live model proposal, use `propose --request 'Add a recovery note to incident 7'` with `OPENAI_API_KEY` configured. Try a second decision on the same job; it is rejected.

Use either a nonblank `--request` or all three manual fields (`--kind`, `--incident-id`, and `--reason`). Mixed modes and missing fields are rejected before creating a database or calling the model.

## Trade-offs, limitations, and next production steps

This is an auditable command ledger, not an incident management integration: approved actions are recorded in `incident_actions` but are not sent to a real incident platform. The CLI approver name is not authentication. A production system would bind approval to a logged-in principal, add expiry and role checks, validate the incident against a source of truth, and dispatch approved commands through an outbox with idempotent retries. Add a persistent LangGraph checkpointer when the workflow has long-running graph state that cannot be reconstructed from the business record.

## Interview preparation

Explain where model authority ends, why a second model review is useful but cannot authorize a write, why a Pydantic schema is necessary but insufficient for authorization, how single-use approval is enforced, how crash recovery works from durable business state, and how an outbox avoids losing approved actions.

## Verify

Run `python -m pytest -q` and `python -m ruff check .` from this repository.
