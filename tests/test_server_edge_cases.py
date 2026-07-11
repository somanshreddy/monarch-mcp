"""Server edge-case unit tests.

Covers _get_monarch_client (keyring-only), check_auth_status/
debug_session_loading branches, update_transaction goal_id,
refresh_accounts empty, and main().
"""
# pylint: disable=missing-function-docstring

import json
from unittest.mock import patch

import pytest

from monarch_mcp.server import main
from monarch_mcp.server import _get_monarch_client
from monarch_mcp.auth_server import with_auth_recovery


# ===================================================================
# get_monarch_client — keyring is the only credential store
# ===================================================================


async def test_get_client_no_credentials(mock_monarch_client):
    """No keyring token → trigger_auth_flow + RuntimeError."""
    with patch("monarch_mcp.secure_session.keyring") as mock_kr:
        mock_kr.get_password.return_value = None

        with (
            patch("monarch_mcp.server.trigger_auth_flow") as mock_auth,
            pytest.raises(RuntimeError, match="Authentication needed"),
        ):
            await with_auth_recovery(_get_monarch_client())

        mock_auth.assert_called_once()


async def test_get_client_ignores_env_credentials(mock_monarch_client, monkeypatch):
    """Env credentials must NOT authenticate — the browser flow is the only path.

    Regression guard. The removed env-var branch called ``MonarchMoney.login()``
    with library defaults (``use_saved_session=True, save_session=True``), which
    writes the session token to an unencrypted pickle at a CWD-relative path and
    ``pickle.load()``s it back on the next call.
    """
    monkeypatch.setenv("MONARCH_EMAIL", "user@test.com")
    monkeypatch.setenv("MONARCH_PASSWORD", "secret123")

    with (
        patch("monarch_mcp.secure_session.keyring") as mock_kr,
        patch("monarch_mcp.server.MonarchMoney") as mock_mm,
    ):
        mock_kr.get_password.return_value = None

        with (
            patch("monarch_mcp.server.trigger_auth_flow") as mock_auth,
            pytest.raises(RuntimeError, match="Authentication needed"),
        ):
            await with_auth_recovery(_get_monarch_client())

        mock_auth.assert_called_once()
        mock_mm.assert_not_called()


# ===================================================================
# check_auth_status — branches
# ===================================================================


async def test_check_auth_no_token(mcp_client):
    with patch("monarch_mcp.secure_session.keyring") as mock_kr:
        mock_kr.get_password.return_value = None
        result = (await mcp_client.call_tool("check_auth_status")).content[0].text

    assert "No authentication token" in result


async def test_check_auth_exception(mcp_client):
    with patch("monarch_mcp.server.secure_session") as mock_ss:
        mock_ss.load_token.side_effect = RuntimeError("boom")
        result = (await mcp_client.call_tool("check_auth_status")).content[0].text

    assert "Error checking auth status" in result


# ===================================================================
# debug_session_loading — branches
# ===================================================================


async def test_debug_session_no_token(mcp_client):
    with patch("monarch_mcp.secure_session.keyring") as mock_kr:
        mock_kr.get_password.return_value = None
        result = (await mcp_client.call_tool("debug_session_loading")).content[0].text

    assert "No token found" in result


async def test_debug_session_exception(mcp_client):
    with patch("monarch_mcp.server.secure_session") as mock_ss:
        mock_ss.load_token.side_effect = RuntimeError("keyring busted")
        result = (await mcp_client.call_tool("debug_session_loading")).content[0].text

    assert "Keyring access failed" in result
    # The raw exception text and traceback must not leak to the client.
    assert "keyring busted" not in result
    assert "Traceback" not in result


# ===================================================================
# update_transaction — goal_id branch
# ===================================================================


async def test_update_transaction_goal_id(mcp_write_client, mock_monarch_client):
    mock_monarch_client.update_transaction.return_value = {"ok": True}

    result = json.loads(
        (await mcp_write_client.call_tool(
            "update_transaction", {"transaction_id": "txn-1", "goal_id": "goal-42"}
        )).content[0].text
    )

    assert result["ok"] is True
    call_kwargs = mock_monarch_client.update_transaction.call_args[1]
    assert call_kwargs["goal_id"] == "goal-42"


async def test_update_transaction_clear_goal_flag(mcp_write_client, mock_monarch_client):
    # clear_goal=true unlinks the goal via the client-friendly flag, forwarded as goal_id="".
    mock_monarch_client.update_transaction.return_value = {"ok": True}

    result = json.loads(
        (await mcp_write_client.call_tool(
            "update_transaction", {"transaction_id": "txn-1", "clear_goal": True}
        )).content[0].text
    )

    assert result["ok"] is True
    call_kwargs = mock_monarch_client.update_transaction.call_args[1]
    assert call_kwargs["goal_id"] == ""


async def test_update_transaction_clear_goal_conflict(mcp_write_client, mock_monarch_client):
    # Linking and unlinking a goal at once is contradictory — reject loudly.
    result = json.loads(
        (await mcp_write_client.call_tool(
            "update_transaction",
            {"transaction_id": "txn-1", "goal_id": "goal-42", "clear_goal": True},
        )).content[0].text
    )

    assert "error" in result
    mock_monarch_client.update_transaction.assert_not_called()


# ===================================================================
# refresh_accounts — empty account list
# ===================================================================


async def test_refresh_accounts_empty(mcp_client, mock_monarch_client):
    mock_monarch_client.get_accounts.return_value = {"accounts": []}

    result = json.loads(
        (await mcp_client.call_tool("refresh_accounts")).content[0].text
    )

    assert "error" in result
    assert "No accounts found" in result["error"]


# ===================================================================
# main()
# ===================================================================


def test_main_success():
    with (
        patch("monarch_mcp.server.trigger_auth_flow") as mock_auth,
        patch("monarch_mcp.server.mcp") as mock_mcp,
    ):
        main()

    mock_auth.assert_called_once()
    mock_mcp.run.assert_called_once()


def test_main_exception():
    with (
        patch("monarch_mcp.server.trigger_auth_flow"),
        patch("monarch_mcp.server.mcp") as mock_mcp,
    ):
        mock_mcp.run.side_effect = OSError("bind failed")
        with pytest.raises(OSError, match="bind failed"):
            main()
