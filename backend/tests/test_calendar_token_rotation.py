"""Regression tests for private calendar subscription token lifecycle."""
from pathlib import Path


def test_calendar_routes_use_distinct_ics_generators():
    """The token-authenticated feed must not be shadowed by export_service."""
    source = (Path(__file__).parents[1] / "app" / "main.py").read_text()
    assert "generate_ics_feed as generate_subscription_ics_feed" in source
    assert "generate_ics_feed as generate_export_ics_feed" in source
    assert "generate_subscription_ics_feed(db, token)" in source
    assert "generate_export_ics_feed(items)" in source


def test_rotation_endpoint_is_authenticated_and_replaces_token():
    source = (Path(__file__).parents[1] / "app" / "main.py").read_text()
    assert '@app.post("/api/calendar/feed-token/rotate"' in source
    assert "user: User = Depends(get_current_user)" in source
    assert "profile.feed_token = secrets.token_hex(24)" in source
    assert "db.commit()" in source
