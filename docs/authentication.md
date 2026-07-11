# Authentication Architecture

Technical details on how the Monarch MCP Server handles authentication, session management, and security.

## Authentication Flow

1. On startup the server checks for a token in the system keyring
2. If no token is found, a local HTTP server is started on a random port and the browser is opened to a login page
3. The user signs in (with MFA if enabled); the token is saved to the keyring
4. The temporary auth server shuts down automatically
5. If a token later expires, the same flow is re-triggered on the next tool call

Note that the page in step 2 is served by *this* server on `127.0.0.1` — it is **not**
monarch.com, and this is **not** OAuth. Your password is posted to the local process,
which calls the Monarch API with it. The password is never written to disk and is
scrubbed from memory once login completes, but the process does handle it.

## Signing in with Google

If you use "Continue with Google", your Monarch account **has no password**, so the flow
above cannot work — there is nothing to type into it.

**There is also no token to import.** The `Authorization: Token <...>` scheme this server
uses is minted by Monarch's `/auth/login/` endpoint in exchange for an email and password.
A Google sign-in never hits that endpoint, so no such token is ever created for the
account. The web app authenticates a Google session with a Django **session cookie**
(`session_id` + `csrftoken`) instead — a different auth scheme entirely, not a different
way of carrying the same credential. Inspecting a `graphql` request in DevTools for a
Google-signed-in account shows a `Cookie` header and no `Authorization` header.

Replicating that cookie session from Python is possible in principle (the gql transport
accepts arbitrary headers) but is a browser-session-replication hack: it has to satisfy
Django's CSRF and Referer checks, it risks Cloudflare bot management (`cf_clearance` is
bound to IP and User-Agent, and aiohttp's TLS fingerprint is not a browser's), and Django
sessions are typically far shorter-lived than the `trusted_device=True` token.

The supported path is to **set a password on the Monarch account** (Settings → Security),
which makes the standard login flow work and mints a long-lived token.

> **Enable Two-Factor Authentication before you set the password, not after.**
> A Google-only account's second factor is Google's. Adding a password creates a second
> way in, and without Monarch MFA enabled that path is *single-factor* — a net downgrade
> to account security. With MFA on, you are at password + TOTP. Use a long random password
> from a password manager.

## Importing an existing token (optional)

If you already have a valid `Authorization: Token` value — i.e. the account has a password
and you would rather not type it into the login form — you can store it directly:

```bash
monarch-mcp-import-token
```

The script reads the token from stdin — never from `sys.argv`, which is visible to other
processes via `ps` and lands in shell history — rejects JWT-shaped values (that is the
1-hour features/Ably token, not the session token), validates it with a live API call, and
writes it to the keyring only if it works. This does not apply to Google-only accounts,
which have no such token (see above).

## Session Management

- Tokens are stored securely in the system keyring (service: `com.mcp.monarch-mcp`)
- The monarchmoneycommunity library hardwires `trusted_device=True`, which produces long-lived tokens that last weeks to months
- Sessions persist across Claude Desktop restarts
- Expired tokens are detected automatically and cleared, triggering re-authentication

## Security

- Credentials are entered in your local browser, never transmitted through Claude Desktop
- The auth server binds to `127.0.0.1` only (not accessible from the network)
- The loopback endpoints enforce a Host allowlist (DNS-rebinding), an Origin check, and an
  `application/json` Content-Type (forcing a CORS preflight this server fails) — closing login-CSRF
- MFA/2FA fully supported; only a one-time TOTP code is used, no MFA secret is stored
- The password is held in memory only long enough to span the MFA challenge, then scrubbed
- Token stored in the OS keyring, not in plain-text files

## The keyring is the only credential store

There is deliberately no email/password fallback (no `MONARCH_EMAIL` / `MONARCH_PASSWORD`, no
CLI login script). Those paths called `monarchmoney.login()` with library defaults —
`use_saved_session=True, save_session=True` — which:

1. Persists the session token as an **unencrypted pickle** at `.mm/mm_session.pickle`, resolved
   against the process's current working directory (under Claude Desktop, not a path you chose).
2. `pickle.load()`s that file back on the next login, *before any credential check*. `pickle.load()`
   on a file you do not control is arbitrary code execution — so the file is not just a token leak,
   it is a code-execution sink in a process holding your Monarch session.

The browser flow avoids both by passing `use_saved_session=False, save_session=False`. Removing the
fallback means no code path in this server can write or read that pickle.

A regression guard (`tests/test_server_edge_cases.py::test_get_client_ignores_env_credentials`)
asserts that setting `MONARCH_EMAIL` / `MONARCH_PASSWORD` does **not** authenticate.
