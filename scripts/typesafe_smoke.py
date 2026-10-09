"""Smoke test for the ``typesafe`` engine (ADR-0040, #224), against the live API.

The unit tests check ``TypeSafeJudge`` against the documented request and
response; this checks it against the real thing, where the key is:

1. ``GET /v1/models``: the key works, and the model names the account lists.
2. One decision 2 sample through the same Redactor the run applies, asked by
   ``TypeSafeJudge`` itself, so the pinned ``JEV_MODEL``, the probability it
   reads and the price it computes are the ones that ship.

It prints one JSON object meant for a PR: the Judgment and the raw response it
was made from. The key is read from the environment and never printed.

Usage, from the repo root, with the key in ``.env``:

    set -a; . ./.env; set +a
    uv run python scripts/typesafe_smoke.py
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from opspilot.judgment import (
    DECISIONS_DIR,
    JEV_MODEL,
    JUDGMENT_TIMEOUT_S,
    WORK_ITEM_TYPE_FILE,
    JudgmentError,
    TypeSafeJudge,
    load_question,
)
from opspilot.redaction import Redactor

MODELS_URL = "https://api.typesafe.ai/v1/models"

# A synthetic request with an email in it, so the redaction is visible too.
SAMPLE = (
    "Subject: Need Jira access\n\n"
    "Please add me to the Jira project. Reach me at jane.doe@example.com."
)


def main() -> int:
    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not key:
        print("TYPESAFE_API_KEY is not set (try: set -a; . ./.env; set +a)", file=sys.stderr)
        return 2
    raw: list[Any] = []

    def keep(response: httpx.Response) -> None:
        response.read()
        try:
            raw.append(response.json())
        except ValueError:
            raw.append(response.text[:200])

    report: dict[str, Any] = {
        "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "jev_model": JEV_MODEL,
    }
    with httpx.Client(event_hooks={"response": [keep]}) as client:
        try:
            r = client.get(MODELS_URL, headers={"Authorization": f"Bearer {key}"}, timeout=10)
            report["models"] = (
                [m["name"] for m in r.json()["models"]]
                if r.is_success
                else f"HTTP {r.status_code}: {r.text[:200]}"
            )
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
            report["models"] = f"failed: {e!r}"
        question = load_question(Path(DECISIONS_DIR) / WORK_ITEM_TYPE_FILE)
        state = Redactor.from_yaml().redact(SAMPLE).text
        raw.clear()
        report["d2"] = {"question_version": question.version, "state_sent": state}
        try:
            j = TypeSafeJudge(key, client=client).judge(
                question, state, timeout_s=JUDGMENT_TIMEOUT_S
            )
            report["d2"]["judgment"] = j.as_trace()
        except JudgmentError as e:
            report["d2"]["error"] = str(e)
        report["d2"]["response"] = raw[0] if raw else None
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if "judgment" in report["d2"] else 1


if __name__ == "__main__":
    sys.exit(main())
