from types import SimpleNamespace

import pytest

from personal_agent.adapters.web.routes._shared import (
    resolve_query_user_id,
    resolve_requested_principal,
)
from personal_agent.kernel.config_env import _parse_api_keys


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
        state=SimpleNamespace(
            principal=(
                {"tenant_id": "tenant-1", "user_id": user_id}
                if user_id
                else None
            ),
            is_admin=is_admin,
        )
    )


def test_api_key_configuration_requires_typed_principal_json():
    parsed = _parse_api_keys(
        '{"key":{"tenant_id":"tenant-1","user_id":"alice"}}'
    )

    assert parsed == {
        "key": {"tenant_id": "tenant-1", "user_id": "alice"}
    }
    with pytest.raises(ValueError):
        _parse_api_keys("key:alice")


def test_resolve_query_user_allows_requested_user_when_auth_disabled():
    resolved = resolve_query_user_id(
        _request(user_id="default"),
        _settings(),
        "frontend-test-user",
    )

    assert resolved == "frontend-test-user"


def test_requested_principal_allows_explicit_user_only_when_auth_disabled():
    resolved = resolve_requested_principal(
        _request(user_id="default"),
        _settings(),
        "frontend-test-user",
    )

    assert resolved.tenant_id == "tenant-1"
    assert resolved.user_id == "frontend-test-user"

    with pytest.raises(PermissionError):
        resolve_requested_principal(
            _request(user_id="alice"),
            _settings(
                api_keys={
                    "key": {
                        "tenant_id": "tenant-1",
                        "user_id": "alice",
                    }
                }
            ),
            "bob",
        )


def test_resolve_query_user_ignores_requested_user_for_non_admin_when_auth_enabled():
    resolved = resolve_query_user_id(
        _request(user_id="alice"),
        _settings(api_keys={"key": {"tenant_id": "tenant-1", "user_id": "alice"}}),
        "bob",
    )

    assert resolved == "alice"


def test_resolve_query_user_allows_requested_user_for_admin():
    resolved = resolve_query_user_id(
        _request(user_id="admin", is_admin=True),
        _settings(admin_api_keys={
            "admin-key": {"tenant_id": "tenant-1", "user_id": "admin"}
        }),
        "bob",
    )

    assert resolved == "bob"
