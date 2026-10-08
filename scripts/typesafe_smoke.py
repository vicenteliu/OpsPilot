"""Smoke test for the ``typesafe`` engine (ADR-0040, #224): one real call to each endpoint.

1. ``GET /v1/models``: the key works, and the model names it may ask for.
2. ``POST /v1/systemone``: one decision 2 sample, asked the way
   ``TypeSafeJudge`` asks it (d2.yaml's text and answers), through the same
   Redactor the run applies.

It prints one JSON object meant to be pasted into the PR: the raw answer
(both ``confidence`` and ``probabilities``, since which one the threshold reads
is still open), the token usage and the latency. The key is read from the
environment and never printed.

Usage, from the repo root, with the key in ``.env``:

    set -a; . ./.env; set +a
    uv run python scripts/typesafe_smoke.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from opspilot.errors import OpsPilotError
from opspilot.judgment import DECISIONS_DIR, WORK_ITEM_TYPE_FILE, load_question
from opspilot.providers.typesafe import DEFAULT_MODEL, TypeSafeClient
from opspilot.redaction import Redactor

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
    client = TypeSafeClient(key)
    question = load_question(Path(DECISIONS_DIR) / WORK_ITEM_TYPE_FILE)
    state = Redactor.from_yaml().redact(SAMPLE).text
    report: dict[str, object] = {"run_at": datetime.now(UTC).isoformat(timespec="seconds")}
    try:
        report["models"] = client.models()
        started = time.monotonic()
        data = client.system_one(
            state,
            {
                question.id: {
                    "type": "choice",
                    "instructions": question.text,
                    "criteria": question.answers,
                }
            },
            model=DEFAULT_MODEL,
            timeout_s=client.timeout_s,
        )
        report["d2"] = {
            "question_version": question.version,
            "state_sent": state,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "response": data,
        }
    except OpsPilotError as e:
        report["error"] = str(e)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 1
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
