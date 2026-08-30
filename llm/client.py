"""Claude client with three modes, in priority order:

  live    — ANTHROPIC_API_KEY set and MOCK_MODE != 1: real API calls via the
            official `anthropic` SDK. Every live response is auto-saved as a
            fixture, so one real run refreshes the offline demo.
  fixture — cached JSON response for this task exists in llm/fixtures/.
  absent  — returns None; the caller falls back to a deterministic heuristic
            (llm/fallback.py). The demo therefore never hard-fails.

The LLM is never the source of quantitative truth: prompts contain only
pre-computed numbers, and returned JSON is counted/validated in Python.
"""
import json
import os
import re
import time

import telemetry

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(BASE, "llm", "fixtures")

HAIKU = "claude-haiku-4-5"
SONNET = "claude-sonnet-5"

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE, ".env"))
except ImportError:
    pass


def _mock_mode() -> bool:
    if os.environ.get("MOCK_MODE", "").strip() == "1":
        return True
    return not os.environ.get("ANTHROPIC_API_KEY", "").strip()


def _parse_json(text: str):
    text = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.M).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in response")
    return json.loads(text[start:end + 1])


class LLMClient:
    def __init__(self):
        self.mock = _mock_mode()
        self._client = None
        if not self.mock:
            import anthropic
            self._client = anthropic.Anthropic()

    @property
    def mode(self) -> str:
        return "mock" if self.mock else "live"

    def json_call(self, task_key: str, system: str, user: str, model: str = HAIKU,
                  max_tokens: int = 2000, effort: str = None):
        """Returns parsed JSON dict, or None when no fixture exists in mock mode."""
        t0 = time.perf_counter()
        if self.mock:
            path = os.path.join(FIXTURES, f"{task_key}.json")
            if not os.path.exists(path):
                return None
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            telemetry.record(task_key, model, (time.perf_counter() - t0) * 1000,
                             in_tok=len(system + user) // 4,
                             out_tok=len(json.dumps(data)) // 4, mode="fixture")
            return data

        try:
            kwargs = {}
            if effort:  # effort only supported on Sonnet 5 / Opus-tier models
                kwargs["output_config"] = {"effort": effort}
            resp = self._client.messages.create(
                model=model, max_tokens=max_tokens, system=system,
                messages=[{"role": "user", "content": user}], **kwargs,
            )
            latency = (time.perf_counter() - t0) * 1000
            text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
            data = _parse_json(text)
        except Exception as e:  # demo insurance: any API/parse failure -> fallback path
            print(f"[llm] live call failed for {task_key}: {e}; using fallback")
            telemetry.record(task_key, model, (time.perf_counter() - t0) * 1000,
                             0, 0, mode="error")
            path = os.path.join(FIXTURES, f"{task_key}.json")
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    return json.load(f)
            return None
        telemetry.record(task_key, model, latency,
                         resp.usage.input_tokens, resp.usage.output_tokens, mode="live")
        # fixtures are only written by record_fixtures.py — an app session running
        # live must never overwrite the curated offline demo
        if os.environ.get("RECORD_FIXTURES", "") == "1":
            os.makedirs(FIXTURES, exist_ok=True)
            with open(os.path.join(FIXTURES, f"{task_key}.json"), "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        return data
