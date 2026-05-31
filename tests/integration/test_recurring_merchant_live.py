"""Live e2e tests for recurring-merchant tools — read-tool edges + live error paths.

``find_merchant_id_by_name`` is a read tool, so its distinct-merchant / limit /
empty-result behaviour is exercised directly against the live API. The write tool
``update_recurring_merchant`` is exercised only on its **invalid-id error path** —
a real merchant's recurring schedule has no ``MCP-Test-`` handle to clean up, so the
suite never mutates one (that happy-path flow lives in the agent skill's Phase 14).
"""
# pylint: disable=missing-function-docstring,redefined-outer-name

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
async def a_merchant_name(live_mcp_client, call_json):
    """A merchant name pulled from recent transactions (skip if the account has none)."""
    txns = await call_json(live_mcp_client, "get_transactions", {"limit": 50})
    for txn in txns:
        name = txn.get("merchant")
        if name:
            return name
    pytest.skip("live account has no transactions with a merchant to search for")


async def test_find_merchant_id_by_name_distinct(live_mcp_client, call_json, a_merchant_name):
    merchants = await call_json(
        live_mcp_client, "find_merchant_id_by_name", {"name": a_merchant_name}
    )
    assert isinstance(merchants, list)
    assert merchants, f"no merchants found for a name taken from a real txn: {a_merchant_name!r}"
    ids = [m["merchant_id"] for m in merchants]
    assert all(ids), merchants               # every entry carries a non-empty merchant_id
    assert len(ids) == len(set(ids)), ids    # ids are distinct (deduped by the tool)


async def test_find_merchant_id_by_name_respects_limit(
    live_mcp_client, call_json, a_merchant_name
):
    merchants = await call_json(
        live_mcp_client, "find_merchant_id_by_name", {"name": a_merchant_name, "limit": 1}
    )
    assert isinstance(merchants, list)
    assert len(merchants) <= 1


async def test_find_merchant_id_by_name_empty_for_nonsense(live_mcp_client, call_json):
    merchants = await call_json(
        live_mcp_client,
        "find_merchant_id_by_name",
        {"name": "zzzz-no-such-merchant-zzzz-MCP-Test"},
    )
    assert merchants == []


async def test_update_recurring_merchant_invalid_id_is_graceful(
    live_write_client, call_text, maybe_json
):
    text = await call_text(
        live_write_client,
        "update_recurring_merchant",
        {
            "merchant_id": "000000000000000000",
            "name": "MCP-Test-NoSuchMerchant",
            "is_recurring": False,
        },
    )
    # Robustness contract: a bogus merchant id must not leak a raw traceback. The tool
    # returns either a decorator "Error ..." string or a parseable JSON payload (a
    # rejection dict, or a benign object if Monarch no-ops the unknown id).
    assert "Traceback" not in text, text[:300]
    data = maybe_json(text)
    assert text.startswith("Error ") or isinstance(data, (dict, list)), text[:300]
