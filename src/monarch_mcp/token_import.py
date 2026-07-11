"""Import an existing Monarch session token into the system keyring.

Use this when you already hold a valid ``Authorization: Token`` value and would
rather not type a password into the login form.

This does **not** work for accounts that sign in with Google. The token scheme
is minted by Monarch's ``/auth/login/`` endpoint in exchange for an email and
password; a Google sign-in never hits that endpoint, so no token exists for the
account. Those sessions are authenticated with a Django session cookie instead.
See ``docs/authentication.md``.

The token is read from stdin (never from ``sys.argv``, which is visible to
other processes via ``ps`` and lands in shell history), validated with a live
API call, and only written to the keyring if it actually works.
"""

import asyncio
import getpass
import sys

from monarchmoney import MonarchMoney

from monarch_mcp.secure_session import secure_session, is_auth_error

_INSTRUCTIONS = """\
Import a Monarch session token into your system keyring.

To get the token:

  1. Sign in to https://app.monarch.com in your browser as you normally do.
  2. Open DevTools (Cmd-Opt-I) and go to the Network tab.
  3. Reload the page, then click any request named "graphql".
  4. Under Request Headers, find:  Authorization: Token <TOKEN>
  5. Copy the <TOKEN> value only (not the word "Token").

The token is validated against the Monarch API before it is stored.
"""


async def _validate(token: str) -> bool:
    """Return True if the token authenticates against the live API."""
    client = MonarchMoney(token=token)
    try:
        await client.get_accounts()
        return True
    except Exception as exc:  # pylint: disable=broad-exception-caught
        if is_auth_error(exc):
            return False
        raise


def main() -> int:
    """Prompt for a token, validate it, and store it in the keyring."""
    print(_INSTRUCTIONS)

    # getpass: no echo, not in argv, not in shell history.
    token = getpass.getpass("Paste your Monarch token (input hidden): ").strip()

    if not token:
        print("No token entered — nothing was stored.", file=sys.stderr)
        return 1

    # A token with two dots is the short-lived (1-hour) features/Ably JWT, not
    # the long-lived session token. The library refuses to persist these; catch
    # it here with a message that says what to do instead.
    if token.count(".") == 2:
        print(
            "\nThat looks like a JWT (it has two dots) — most likely the "
            "short-lived\nfeatures token, which expires in about an hour and "
            "will not work here.\nLook for the 'Authorization: Token ...' "
            "header on a graphql request instead.",
            file=sys.stderr,
        )
        return 1

    print("\nValidating token against the Monarch API...")
    try:
        valid = asyncio.run(_validate(token))
    except Exception as exc:  # pylint: disable=broad-exception-caught
        print(f"\nCould not validate the token: {exc}", file=sys.stderr)
        print("Nothing was stored.", file=sys.stderr)
        return 1

    if not valid:
        print(
            "\nMonarch rejected that token (401/403). It may be truncated, "
            "expired,\nor copied from the wrong header. Nothing was stored.",
            file=sys.stderr,
        )
        return 1

    secure_session.save_token(token)
    print("\nToken validated and saved to your system keyring.")
    print("The MCP server will now start authenticated — no browser login needed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
