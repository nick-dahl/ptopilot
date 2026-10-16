import json

import httpx
import pytest

from ptopilot.notify.email import API_URL, EmailError, ResendEmailer


def emailer(status=200, body=None, seen=None):
    def handler(request):
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json=body if body is not None else {"id": "msg_1"})

    return ResendEmailer(
        "re_key", "ptopilot <onboarding@resend.dev>", httpx.Client(transport=httpx.MockTransport(handler))
    )


def test_send_posts_message_and_returns_id():
    seen = []
    assert emailer(seen=seen).send("me@example.com", "Hi", "<p>Hi</p>", "Hi") == "msg_1"
    req = seen[0]
    assert str(req.url) == API_URL
    assert req.headers["Authorization"] == "Bearer re_key"
    sent = json.loads(req.content)
    assert sent == {
        "from": "ptopilot <onboarding@resend.dev>",
        "to": ["me@example.com"],
        "subject": "Hi",
        "html": "<p>Hi</p>",
        "text": "Hi",
    }


def test_http_error_raises_email_error():
    with pytest.raises(EmailError, match="HTTP 403"):
        emailer(status=403, body={"message": "domain not verified"}).send("x@example.com", "s", "h", "t")


def test_empty_key_is_rejected():
    with pytest.raises(ValueError, match="RESEND_API_KEY"):
        ResendEmailer("", "x@example.com")
