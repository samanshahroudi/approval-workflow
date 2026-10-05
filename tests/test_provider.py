from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from approval_workflow.workflow import Action, RiskReview, plan_live, review_live


@pytest.mark.parametrize("operation", ["plan", "review"])
@pytest.mark.parametrize("outcome", ["success", "provider_error", "no_output"])
def test_provider_clients_close_on_every_outcome(monkeypatch, operation, outcome):
    client = Mock()
    factory = Mock(return_value=client)
    monkeypatch.setattr("openai.OpenAI", factory)
    action = Action(kind="add_note", incident_id=7, reason="Recovery confirmed")
    expected = action if operation == "plan" else RiskReview(
        safe_to_propose=True, rationale="Clear recovery note")
    client.responses.parse.return_value = SimpleNamespace(
        output_parsed=None if outcome == "no_output" else expected)
    if outcome == "provider_error":
        client.responses.parse.side_effect = RuntimeError("provider unavailable")
    invoke = lambda: plan_live("Add recovery note") if operation == "plan" else review_live(action)
    if outcome == "success":
        assert invoke() == expected
    elif outcome == "no_output":
        with pytest.raises(ValueError, match="no .* returned"):
            invoke()
    else:
        with pytest.raises(RuntimeError, match="provider unavailable"):
            invoke()
    factory.assert_called_once_with(timeout=20)
    assert client.responses.parse.call_args.kwargs["text_format"] is type(expected)
    client.close.assert_called_once_with()
