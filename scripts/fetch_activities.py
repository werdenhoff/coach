#!/usr/bin/env python3
"""
Sync Strava activities into this repository.

On each run we:
  1. Refresh the short-lived access token using the long-lived refresh token.
  2. Determine the timestamp of the newest activity we already have
     (or 90 days ago on the very first run).
  3. Page through `/athlete/activities` for everything newer than that.
  4. For each new activity, fetch the detailed view and write it as
     `data/activities/{id}.json`.
  5. Rebuild `data/summary.json` — a compact, newest-first index that's cheap
     to pull down and eyeball.

Only Python's stdlib is used, so no requirements.txt is needed.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path


# --- Config ----------------------------------------------------------------

CLIENT_ID = os.environ["STRAVA_CLIENT_ID"]
CLIENT_SECRET = os.environ["STRAVA_CLIENT_SECRET"]
REFRESH_TOKEN = os.environ["STRAVA_REFRESH_TOKEN"]
USER_SLUG = os.environ["USER_SLUG"]

REPO_ROOT = Path(__file__).resolve().parent.parent
ACTIVITIES_DIR = REPO_ROOT / "data" / USER_SLUG / "activities"
SUMMARY_PATH = REPO_ROOT / "data" / USER_SLUG / "summary.json"

# On first run, pull the last 90 days so we get meaningful baseline volume.
FIRST_RUN_LOOKBACK_DAYS = 90

# Strava rate limits (non-premium partner app): 100 requests / 15 min, 1000 / day.
# A 0.4 s pause between detail fetches keeps us well under that.
DETAIL_FETCH_DELAY_S = 0.4


# --- Thin HTTP helpers -----------------------------------------------------

def _http_post(url: str, data: dict) -> dict:
    req = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(data).encode(),
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def _http_get(url: str, access_token: str, params: dict | None = None) -> dict | list:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {access_token}"},
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


# --- Strava API ------------------------------------------------------------

def refresh_access_token() -> str:
    resp = _http_post(
        "https://www.strava.com/api/v3/oauth/token",
        {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "refresh_token": REFRESH_TOKEN,
            "grant_type": "refresh_token",
        },
    )
    return resp["access_token"]


def list_activities_since(access_token: str, after_unix_ts: int) -> list[int]:
    """Return activity IDs with start_date > after_unix_ts, oldest first."""
    ids: list[int] = []
    page = 1
    while True:
        batch = _http_get(
            "https://www.strava.com/api/v3/athlete/activities",
            access_token,
            {"after": after_unix_ts, "page": page, "per_page": 100},
        )
        if not batch:
            break
        ids.extend(a["id"] for a in batch)
        if len(batch) < 100:
            break
        page += 1
        time.sleep(0.3)
    # Strava returns newest first on this endpoint; reverse so we fetch in
    # chronological order (nicer for commit diffs).
    return list(reversed(ids))


def fetch_activity_detail(activity_id: int, access_token: str) -> dict:
    return _http_get(
        f"https://www.strava.com/api/v3/activities/{activity_id}",
        access_token,
        {"include_all_efforts": "false"},
    )


# --- Local storage ---------------------------------------------------------

def newest_local_timestamp() -> int:
    """Unix ts of the newest activity we already have, or 90 days ago."""
    fallback = int((datetime.now(timezone.utc)
                    - timedelta(days=FIRST_RUN_LOOKBACK_DAYS)).timestamp())
    if not SUMMARY_PATH.exists():
        return fallback
    with open(SUMMARY_PATH) as f:
        summary = json.load(f)
    if not summary:
        return fallback
    latest_iso = summary[0]["start_date"]  # summary is newest-first
    dt = datetime.fromisoformat(latest_iso.replace("Z", "+00:00"))
    # +1 s so we don't refetch the same activity
    return int(dt.timestamp()) + 1


def save_activity(activity: dict) -> Path:
    ACTIVITIES_DIR.mkdir(parents=True, exist_ok=True)
    path = ACTIVITIES_DIR / f"{activity['id']}.json"
    with open(path, "w") as f:
        json.dump(activity, f, indent=2, ensure_ascii=False)
    return path


def rebuild_summary() -> int:
    """Rebuild the compact summary index from all detailed JSON files on disk."""
    entries = []
    for path in sorted(ACTIVITIES_DIR.glob("*.json")):
        with open(path) as f:
            a = json.load(f)
        entries.append({
            "id": a["id"],
            "name": a.get("name"),
            "type": a.get("type"),
            "sport_type": a.get("sport_type"),
            "start_date": a.get("start_date"),             # UTC
            "start_date_local": a.get("start_date_local"), # athlete's local time
            "distance_m": a.get("distance"),
            "moving_time_s": a.get("moving_time"),
            "elapsed_time_s": a.get("elapsed_time"),
            "total_elevation_gain_m": a.get("total_elevation_gain"),
            "average_speed_mps": a.get("average_speed"),
            "max_speed_mps": a.get("max_speed"),
            "average_heartrate": a.get("average_heartrate"),
            "max_heartrate": a.get("max_heartrate"),
            "average_cadence": a.get("average_cadence"),
            "suffer_score": a.get("suffer_score"),
            "has_heartrate": a.get("has_heartrate"),
            "workout_type": a.get("workout_type"),
        })
    entries.sort(key=lambda e: e["start_date"] or "", reverse=True)
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(SUMMARY_PATH, "w") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)
    return len(entries)


# --- Entry point -----------------------------------------------------------

def main() -> int:
    access_token = refresh_access_token()

    after_ts = newest_local_timestamp()
    print(f"Looking for activities after {datetime.fromtimestamp(after_ts, tz=timezone.utc).isoformat()}")

    new_ids = list_activities_since(access_token, after_ts)
    print(f"Found {len(new_ids)} new activities")

    for i, activity_id in enumerate(new_ids, 1):
        activity = fetch_activity_detail(activity_id, access_token)
        save_activity(activity)
        print(f"  [{i}/{len(new_ids)}] {activity['start_date_local']} — "
              f"{activity.get('sport_type')} — {activity.get('name')}")
        time.sleep(DETAIL_FETCH_DELAY_S)

    total = rebuild_summary()
    print(f"Summary rebuilt: {total} total activities on disk")
    return 0


if __name__ == "__main__":
    sys.exit(main())
