#!/usr/bin/env python3
"""
Every minute: request the MCP server URL, find its OAuth protected-resource
metadata (via the WWW-Authenticate header, with well-known fallbacks), read the
"resource" value, and save it to disk.

Files written (in the current directory):
  resource.txt        - the latest resource value found (overwritten on change)
  resource_log.jsonl  - one JSON line per check (time, status, resource, note)

No third-party packages needed. Stop with Ctrl+C.
"""
import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlparse

MCP_URL = "https://n8n.pachca.com/mcp-server/http"
INTERVAL_SECONDS = 60
TIMEOUT = 15
LATEST_FILE = "resource.txt"
LOG_FILE = "resource_log.jsonl"


def fetch(url):
    """GET a URL and return (status, headers, body) even for 4xx/5xx."""
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json, text/event-stream",
            "User-Agent": "mcp-resource-monitor/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, r.headers, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read().decode("utf-8", "replace")


def metadata_candidates(headers):
    """URLs where the protected-resource metadata may live."""
    header = headers.get("WWW-Authenticate", "")
    m = re.search(r'resource_metadata="([^"]+)"', header)
    if m:
        return [m.group(1)]
    p = urlparse(MCP_URL)
    base = f"{p.scheme}://{p.netloc}/.well-known/oauth-protected-resource"
    return [base + p.path, base]


def check_once():
    entry = {
        "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": None,
        "resource": None,
        "note": None,
    }
    status, headers, body = fetch(MCP_URL)
    entry["status"] = status
    entry["note"] = body.strip()[:200] or None

    for url in metadata_candidates(headers):
        try:
            m_status, _, m_body = fetch(url)
            if m_status == 200:
                resource = json.loads(m_body).get("resource")
                if resource:
                    entry["resource"] = resource
                    entry["note"] = f"metadata from {url}"
                    break
        except (ValueError, urllib.error.URLError, OSError):
            continue
    return entry


def read_latest():
    try:
        with open(LATEST_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return None


def main(runs=None):
    print(f"Checking {MCP_URL} every {INTERVAL_SECONDS}s. Ctrl+C to stop.")
    count = 0
    while True:
        started = time.monotonic()
        try:
            entry = check_once()
        except (urllib.error.URLError, OSError) as e:
            entry = {
                "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "status": None,
                "resource": None,
                "note": f"request failed: {e}",
            }

        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

        if entry["resource"] and entry["resource"] != read_latest():
            with open(LATEST_FILE, "w", encoding="utf-8") as f:
                f.write(entry["resource"] + "\n")
            print(f"[{entry['time']}] NEW resource saved: {entry['resource']}")
        else:
            print(f"[{entry['time']}] status={entry['status']} "
                  f"resource={entry['resource']} note={entry['note']}")

        count += 1
        if runs and count >= runs:
            break
        time.sleep(max(1, INTERVAL_SECONDS - (time.monotonic() - started)))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=None,
                        help="stop after N checks (default: run forever)")
    args = parser.parse_args()
    try:
        main(args.runs)
    except KeyboardInterrupt:
        print("\nStopped.")
