from types import SimpleNamespace

from personal_agent.adapters.web.routes._shared import resolve_query_user_id


def _settings(api_keys=None, admin_api_keys=None, default_user="default"):
    return SimpleNamespace(
        default_user=default_user,
        web=SimpleNamespace(
            api_keys=api_keys or {},
            admin_api_keys=admin_api_keys or {},
        ),
    )


def _request(user_id=None, is_admin=False):
    return SimpleNamespace(
        state=SimpleNamespace(user_id=user_id, is_admin=is_admin)
    )


def test_resolve_query_user_allows_requested_user_when_auth_disabled():
    resolved = resolve_query_user_id(
        _request(user_id="default"),
        _settings(),
        "frontend-test-user",
    )

    assert resolved == "frontend-test-user"


def test_resolve_query_user_ignores_requested_user_for_non_admin_when_auth_enabled():
    resolved = resolve_query_user_id(
        _request(user_id="alice"),
        _settings(api_keys={"key": "alice"}),
        "bob",
    )

    assert resolved == "alice"


def test_resolve_query_user_allows_requested_user_for_admin():
    resolved = resolve_query_user_id(
        _request(user_id="admin", is_admin=True),
        _settings(admin_api_keys={"admin-key": "admin"}),
        "bob",
    )

    assert resolved == "bob"
