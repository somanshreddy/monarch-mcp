"""Stand-alone login: open the browser flow and wait for it to finish.

The auth server in :mod:`monarch_mcp.auth_server` runs on a daemon thread, so
it only lives as long as the process that started it. When the MCP server
itself starts that flow, an MCP client that stops the server between tool calls
(Claude Code does this) takes the login page down with it — the browser tab is
left pointing at a dead port, and submitting it fails with a bare
"Connection error". Each restart also picks a fresh random port, so reloading
the stale page never recovers.

This command exists so logging in does not depend on the MCP server's
lifecycle: it starts the same flow in the foreground and blocks until the token
lands in the keyring (or the auth server times out), keeping the login page
alive for as long as the user needs it.
"""

import logging
import sys
import time

from monarch_mcp.auth_server import trigger_auth_flow
from monarch_mcp.secure_session import secure_session

# Match the auth server's own window (auth_server._AUTH_TIMEOUT).
_TIMEOUT_SECONDS = 600
_POLL_SECONDS = 1.0


def main() -> int:
    """Run the browser login flow and wait for a token to be stored."""
    # The auth server logs its URL at INFO. Surface it, so the user can open the
    # page by hand if webbrowser.open() cannot (headless, WSL, remote shell).
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        stream=sys.stderr,
    )

    print("Checking for an existing token...", file=sys.stderr)

    # Validates any stored token; opens the browser login only if there isn't a
    # usable one. Non-blocking — the HTTP server runs on a daemon thread.
    trigger_auth_flow()

    deadline = time.monotonic() + _TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if secure_session.load_token():
            print(
                "\nAuthenticated. Token saved to your system keyring.\n"
                "The MCP server will pick it up on its next start.",
                file=sys.stderr,
            )
            return 0
        time.sleep(_POLL_SECONDS)

    print(
        "\nTimed out after 10 minutes without a completed login. "
        "Nothing was stored.\nRe-run this command to try again.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
