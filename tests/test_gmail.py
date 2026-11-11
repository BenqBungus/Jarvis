import base64
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from jarvis.gmail import GmailService, extract_message, register_gmail_tools, gmail_spoken_result
from jarvis.gmail_auth import GmailError
from jarvis.models import CommandResult
from jarvis.tool_registry import ToolCall, ToolRegistry


def part(text, mime="text/plain", **extra):
    return {"mimeType": mime, "body": {"data": base64.urlsafe_b64encode(text.encode()).decode()}, **extra}


def email(text="Private meeting at 10:00."):
    payload = part(text)
    payload["headers"] = [{"name": "Subject", "value": "Private project"},
                          {"name": "From", "value": "person@example.com"}]
    return {"id": "abc123", "payload": payload}


@pytest.fixture
def gmail():
    api = Mock()
    api.list.return_value.execute.return_value = {"messages": [{"id": "abc123"}]}
    api.get.return_value.execute.return_value = email()
    client = Mock()
    client.users.return_value.messages.return_value = api
    auth = Mock()
    auth.client.return_value = client
    auth.connected.return_value = True
    ai = Mock(summarize_email=Mock(return_value=CommandResult(True, "Meeting at 10:00.")))
    service = GmailService(ai, auth=auth)
    return SimpleNamespace(service=service, api=api, auth=auth, ai=ai, client=client)


def test_search_reads_only_headers_and_returns_expiring_selection(gmail):
    result = gmail.service.search("in:inbox is:unread", 3)
    assert result.ok and result.metadata["private_content"]
    assert "Private meeting" not in result.message
    assert "Private project" in result.message
    gmail.api.list.assert_called_once_with(userId="me", q="in:inbox is:unread", maxResults=3)
    gmail.api.get.assert_called_once_with(userId="me", id="abc123", format="metadata", metadataHeaders=["From", "Subject", "Date"])
    assert gmail.service.selection().metadata["selection_id"] == result.metadata["selection_id"]
    gmail.client.close.assert_called_once()


def test_read_uses_observed_message_and_summary_is_separate(gmail):
    selected = gmail.service.search().metadata["selection_id"]
    result = gmail.service.read(selected, 1)
    assert result.ok and "Private meeting" in result.message
    assert "BEGIN_UNTRUSTED_WEB_CONTENT" in result.message
    gmail.ai.summarize_email.assert_not_called()
    gmail.api.get.assert_called_with(userId="me", id="abc123", format="full")
    summary = gmail.service.read(selected, 1, summarize=True)
    assert summary.ok and summary.metadata["summarized"]
    assert json.loads(gmail.ai.summarize_email.call_args.args[0])["body"] == "Private meeting at 10:00."


@pytest.mark.parametrize("ordinal", [0, -1, 2, True, "1"])
def test_invalid_selection_never_fetches_body(gmail, ordinal):
    selected = gmail.service.search().metadata["selection_id"]
    gmail.auth.client.reset_mock()
    assert not gmail.service.read(selected, ordinal).ok
    gmail.auth.client.assert_not_called()


def test_expired_or_replaced_selection_is_not_reused(gmail, monkeypatch):
    selected = gmail.service.search().metadata["selection_id"]
    gmail.service.search()
    assert not gmail.service.read(selected, 1).ok
    current = gmail.service.selection().metadata["selection_id"]
    monkeypatch.setattr("jarvis.gmail.time.monotonic", lambda: gmail.service._selection["at"] + 601)
    assert not gmail.service.read(current, 1).ok


def test_search_failure_clears_previous_selection_and_hides_provider_body(gmail):
    gmail.service.search()
    gmail.api.list.return_value.execute.side_effect = RuntimeError("secret refresh token and private email")
    result = gmail.service.search()
    assert not result.ok and "secret" not in result.message
    assert not gmail.service.selection().ok


def test_empty_and_partial_searches_are_honest(gmail):
    gmail.api.list.return_value.execute.return_value = {}
    assert "No matching emails" in gmail.service.search().message
    gmail.api.list.return_value.execute.return_value = {"messages": [{"id": "abc123"}], "nextPageToken": "hidden"}
    result = gmail.service.search()
    assert result.metadata["partial"] and "More results" in result.message


def test_disconnect_and_reconnect_clear_selection(gmail):
    gmail.service.search()
    assert gmail.service.disconnect().ok
    gmail.auth.disconnect.assert_called_once()
    assert not gmail.service.selection().ok
    gmail.service.search()
    assert gmail.service.connect("chosen.json").ok
    assert not gmail.service.selection().ok


def test_cancelled_task_does_not_access_mail(gmail):
    gmail.service.cancelled = lambda: True
    assert not gmail.service.search().ok
    gmail.auth.client.assert_not_called()


def test_dry_run_never_reads_credentials_or_calls_providers(gmail):
    gmail.service.dry_run = True
    for result in (gmail.service.status(), gmail.service.connect("anything"), gmail.service.disconnect(),
                   gmail.service.search(), gmail.service.read("fake", 1, summarize=True)):
        assert result.ok
    assert not gmail.auth.mock_calls
    assert not gmail.ai.mock_calls


@pytest.mark.parametrize("query,limit", [("", 5), ("x" * 501, 5), ("ok", 11), ("ok", True)])
def test_invalid_search_is_bounded(gmail, query, limit):
    assert not gmail.service.search(query, limit).ok
    gmail.auth.client.assert_not_called()


def test_mime_text_and_html_do_not_load_external_content():
    html = '<html><head><style>hidden</style></head><body><p>Hello &amp; goodbye</p><script>evil()</script><img src="https://tracker.invalid/pixel"></body></html>'
    extracted = extract_message({"payload": part(html, "text/html")})
    assert extracted["body"] == "Hello & goodbye"
    assert not extracted["attachments_included"]
    assert not extracted["partial"]


def test_mime_attachment_and_long_body_are_marked_partial():
    extracted = extract_message({"payload": {"mimeType": "multipart/mixed", "parts": [
        part("x" * 20000), part("SECRET ATTACHMENT", filename="private.txt")]}})
    assert extracted["partial"]
    assert len(extracted["body"]) == 16000
    assert "SECRET ATTACHMENT" not in extracted["body"]


def test_bulgarian_plaintext_and_malformed_body():
    assert extract_message(email("Здравей, Берк"))["body"] == "Здравей, Берк"
    assert extract_message({"payload": {"mimeType": "text/plain", "body": {"data": "!!!!"}}})["partial"]


def test_encoded_email_subject_is_decoded():
    from email.header import Header
    message = email()
    message["payload"]["headers"][0]["value"] = Header("Покана за среща", "utf-8").encode()
    assert extract_message(message)["subject"] == "Покана за среща"


def test_gmail_registry_has_no_write_or_connect_tools(gmail):
    registry = ToolRegistry()
    register_gmail_tools(registry, gmail.service)
    assert {s.name for s in registry.list_specs()} == {
        "gmail_status", "gmail_selection", "gmail_search", "gmail_read", "gmail_summarize", "gmail_advise", "gmail_disconnect"}
    for name in ("gmail_search", "gmail_read", "gmail_summarize", "gmail_advise", "gmail_disconnect"):
        assert registry.get(name).spec.requires_confirmation
    result = registry.execute(ToolCall("gmail_search", {"limit": "five"}))
    assert not result.ok
    gmail.auth.client.assert_not_called()


def test_auth_error_is_explained(gmail):
    gmail.auth.client.side_effect = GmailError("Connect Gmail first.")
    assert gmail.service.search().message == "Connect Gmail first."


def test_business_advice_reads_selected_email_and_requests_analysis(gmail):
    selected = gmail.service.search().metadata["selection_id"]
    assert gmail.service.selection().metadata["last_read_ordinal"] is None
    result = gmail.service.read(selected, 1, business=True)
    assert result.ok and result.metadata["business_advice"]
    assert gmail.ai.summarize_email.call_args.kwargs == {"business": True}
    assert "Private meeting" in gmail.ai.summarize_email.call_args.args[0]
    assert gmail.service.selection().metadata["last_read_ordinal"] == 1
    gmail.service.search()
    assert gmail.service.selection().metadata["last_read_ordinal"] is None


def test_cancel_during_analysis_does_not_report_completion(gmail):
    selected = gmail.service.search().metadata["selection_id"]

    def finish(_source, **kwargs):
        gmail.service.cancelled = lambda: True
        return CommandResult(True, "PRIVATE RECOMMENDATION")

    gmail.ai.summarize_email.side_effect = finish
    result = gmail.service.read(selected, 1, business=True)
    assert not result.ok and "cancelled" in result.message
    assert "PRIVATE RECOMMENDATION" not in result.message


def test_spoken_email_is_readable_without_changing_ai_tool_result(gmail):
    selected = gmail.service.search().metadata["selection_id"]
    registry = ToolRegistry()
    register_gmail_tools(registry, gmail.service)
    result = registry.execute(ToolCall("gmail_read", {"selection_id": selected, "ordinal": 1}))
    spoken = gmail_spoken_result(result)
    assert spoken.message == "From: person@example.com. Subject: Private project.\nPrivate meeting at 10:00."
    assert "BEGIN_UNTRUSTED" in result.message and "BEGIN_UNTRUSTED" not in spoken.message
    assert spoken.confirmed == result.confirmed and spoken.metadata["private_content"]


def test_spoken_email_redacts_secrets_and_warns_on_partial_reading(gmail):
    selected = gmail.service.search().metadata["selection_id"]
    message = email("password: privatepassword")
    message["payload"]["parts"] = [part("private attachment", filename="secret.txt")]
    gmail.api.get.return_value.execute.return_value = message
    result = gmail.service.read(selected, 1)
    assert "privatepassword" not in result.metadata["gmail_spoken_text"]
    assert "incomplete" in result.metadata["gmail_spoken_text"]


def test_spoken_presentation_does_not_rewrite_non_email_or_error_results():
    result = CommandResult(True, "Original", metadata={"gmail_spoken_text": "replacement"})
    assert gmail_spoken_result(result) is result
    error = CommandResult(False, "Error", metadata={"tool_category": "gmail", "gmail_spoken_text": "replacement"})
    assert gmail_spoken_result(error) is error
