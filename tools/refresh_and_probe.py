"""Refresh the OAuth token, then probe the usage endpoint and dump its shape.

    .venv\\Scripts\\python.exe tools\\refresh_and_probe.py

Prints only structure -- keys, types, sample values for non-sensitive fields.
No token material is printed at any point, including on error paths.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests  # noqa: E402

from claude_usage import config, credentials  # noqa: E402


def describe_shape(value, indent=0, key=""):
    """Recursively print keys and types rather than a raw dump."""
    pad = "  " * indent
    if isinstance(value, dict):
        print(f"{pad}{key}{'{' } dict, {len(value)} keys")
        for k, v in value.items():
            describe_shape(v, indent + 1, f"{k}: ")
        print(f"{pad}}}")
    elif isinstance(value, list):
        print(f"{pad}{key}[ list, {len(value)} items")
        for i, v in enumerate(value[:3]):
            describe_shape(v, indent + 1, f"[{i}] ")
        if len(value) > 3:
            print(f"{pad}  ... {len(value) - 3} more")
        print(f"{pad}]")
    else:
        print(f"{pad}{key}{type(value).__name__} = {value!r}")


print("=== 1. current credential status ===")
print("  ", credentials.describe())

# This is the only tool here that CHANGES anything of yours: it renews your
# Claude login and rewrites ~/.claude/.credentials.json (after backing it up).
# Everything else in tools/ is read-only, so make this one ask first -- running
# every script in a folder to see what they do should not rotate your token.
print("\nThis will renew your Claude login and rewrite:")
print(f"   {config.CREDENTIALS_FILE}")
print(f"   (a backup is written to {config.CREDENTIALS_FILE.name}.bak first)")
if "--yes" not in sys.argv:
    try:
        if input("\nContinue? [y/N] ").strip().lower() not in ("y", "yes"):
            print("Cancelled. Nothing was changed.")
            sys.exit(0)
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled. Nothing was changed.")
        sys.exit(0)

print("\n=== 2. refreshing access token ===")
try:
    creds = credentials.refresh()
except credentials.RefreshFailed as exc:
    print(f"   REFRESH FAILED: {exc}")
    print("\n   Credentials file was NOT modified (or was restored from backup).")
    sys.exit(1)

expires_in = (creds.expires_at - time.time()) / 3600 if creds.expires_at else None
print("   OK -- new access token obtained (value withheld)")
print(f"   plan       : {creds.subscription_type}")
print(f"   expires in : {expires_in:.2f} h" if expires_in else "   expires in : unknown")
print(f"   backup at  : {config.CREDENTIALS_FILE.with_suffix('.json.bak')}")

print("\n=== 3. GET", config.USAGE_URL, "===")
resp = requests.get(
    config.USAGE_URL,
    headers={
        "Authorization": f"Bearer {creds.access_token}",
        "Accept": "application/json",
    },
    timeout=config.REQUEST_TIMEOUT,
)
print(f"   HTTP {resp.status_code}")
print(f"   content-type: {resp.headers.get('content-type')}")

if resp.status_code != 200:
    print("   BODY:", credentials.redact(resp.text)[:600])
    sys.exit(1)

payload = resp.json()

print("\n=== 4. response shape ===")
describe_shape(payload)

print("\n=== 5. raw JSON ===")
print(json.dumps(payload, indent=2)[:4000])

out = Path(__file__).resolve().parent.parent / "state" / "sample_response.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
print(f"\nsaved sample -> {out}")
