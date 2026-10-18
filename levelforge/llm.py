"""
Minimal LLM client with three back-ends:

    groq    - set GROQ_API_KEY   (free tier, fast; default model openai/gpt-oss-120b)
    gemini  - set GEMINI_API_KEY (default model gemini-3.5-flash-lite)
    offline - no key needed; agents fall back to deterministic rule-based logic

Uses only the Python standard library, so there is nothing extra to install.
Override the model with the LLM_MODEL environment variable.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_env(path: str | None = None) -> list[str]:
    """Load KEY=VALUE lines from the project's .env file into os.environ.

    Standard library only (no python-dotenv needed). Variables already set in the
    terminal win over the file. Returns the names that were loaded.
    """
    path = path or os.path.join(PROJECT_ROOT, ".env")
    loaded = []
    if not os.path.isfile(path):
        return loaded
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip().removeprefix("export ").strip()
            value = value.strip().strip('"').strip("'")
            if not key or not value or value.startswith("your_"):
                continue  # skip blanks and the placeholder text
            if key not in os.environ:
                os.environ[key] = value
                loaded.append(key)
    return loaded


load_env()

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# Groq's API sits behind Cloudflare, which rejects Python's default "Python-urllib"
# User-Agent with HTTP 403 "error code: 1010". Always send an explicit one.
USER_AGENT = "LevelForge/1.0 (+https://github.com; python-urllib)"


class LLMError(RuntimeError):
    pass


class LLM:
    def __init__(self, provider: str | None = None, model: str | None = None):
        if provider is None:
            if os.environ.get("GROQ_API_KEY"):
                provider = "groq"
            elif os.environ.get("GEMINI_API_KEY"):
                provider = "gemini"
            else:
                provider = "offline"
        self.provider = provider
        default = {"groq": "openai/gpt-oss-120b", "gemini": "gemini-3.5-flash-lite"}
        self.model = model or os.environ.get("LLM_MODEL") or default.get(provider, "rules")
        self.calls = 0
        self.failures = 0
        self.disabled_reason = ""   # set after a permanent error (bad key, blocked, wrong model)
        self.send_reasoning_effort = True
        self.send_json_mode = True
        self.rate_limit_waits = 0

    @property
    def online(self) -> bool:
        return self.provider in ("groq", "gemini")

    def describe(self) -> str:
        if not self.online:
            return "offline (rule-based agents)"
        if self.disabled_reason:
            return f"{self.provider}:{self.model} (disabled after error, rules used)"
        return f"{self.provider}:{self.model}"

    # ------------------------------------------------------------------
    def _post(self, url: str, payload: dict, headers: dict) -> dict:
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                     headers={"Content-Type": "application/json",
                                              "User-Agent": USER_AGENT, **headers})
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def chat(self, system: str, user: str, temperature: float = 0.4, retries: int = 5,
             json_mode: bool = False) -> str:
        if not self.online:
            raise LLMError("offline mode")
        if self.disabled_reason:
            raise LLMError(self.disabled_reason)
        last = None
        for attempt in range(retries):
            try:
                self.calls += 1
                if self.provider == "groq":
                    payload = {
                        "model": self.model, "temperature": temperature,
                        "max_completion_tokens": 4096,
                        "messages": [{"role": "system", "content": system},
                                     {"role": "user", "content": user}],
                    }
                    if "gpt-oss" in self.model and self.send_reasoning_effort:
                        payload["reasoning_effort"] = "low"  # reasoning model: keep it fast
                    if json_mode and self.send_json_mode:
                        payload["response_format"] = {"type": "json_object"}
                    data = self._post(GROQ_URL, payload,
                                      {"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}"})
                    text = data["choices"][0]["message"].get("content") or ""
                else:
                    cfg = {"temperature": temperature}
                    if json_mode:
                        cfg["responseMimeType"] = "application/json"
                    data = self._post(GEMINI_URL.format(model=self.model), {
                        "systemInstruction": {"parts": [{"text": system}]},
                        "contents": [{"role": "user", "parts": [{"text": user}]}],
                        "generationConfig": cfg,
                    }, {"x-goog-api-key": os.environ["GEMINI_API_KEY"]})
                    text = data["candidates"][0]["content"]["parts"][0].get("text", "")
                if not text.strip():
                    last = "model returned an empty reply"
                    continue  # retry: reasoning models occasionally return no content
                return text
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", "ignore")[:300]
                last = f"HTTP {e.code}: {body}"
                if e.code in (401, 403, 404):
                    # permanent problem: stop calling the API for the rest of the run
                    hint = {401: "API key rejected - check the key in .env",
                            403: "request blocked (403) - see README troubleshooting",
                            404: f"model '{self.model}' not found - set LLM_MODEL in .env"}[e.code]
                    self.disabled_reason = f"{hint}: {body.strip()[:120]}"
                    last = self.disabled_reason
                    print(f"  [LLM] {self.disabled_reason}. Falling back to rule-based agents.", flush=True)
                    break
                low = body.lower()
                if e.code == 400 and "reasoning" in low and self.send_reasoning_effort:
                    self.send_reasoning_effort = False  # parameter not supported: retry without it
                    continue
                if e.code == 400 and ("response_format" in low or "json_object" in low) and self.send_json_mode:
                    self.send_json_mode = False
                    continue
                if e.code == 400 and "json_validate_failed" in low:
                    continue  # model produced invalid JSON in JSON mode: just try again
                if e.code == 400:
                    break  # bad request for this prompt only; next call may work
                if e.code == 429:
                    # free-tier rate limit: wait as long as the server asks (capped)
                    wait = _retry_after(e, body) or 4 * (attempt + 1)
                    self.rate_limit_waits += 1
                    time.sleep(min(wait + 0.5, 30))
                    continue
                time.sleep(2 * (attempt + 1))  # server error
            except Exception as e:  # network, parsing
                last = str(e)
                time.sleep(1 + attempt)
        self.failures += 1
        raise LLMError(last or "unknown LLM error")

    def chat_json(self, system: str, user: str, temperature: float = 0.4):
        system = system + "\nReply with a single valid JSON object only: no prose, no markdown fences."
        text = self.chat(system, user, temperature, json_mode=True)
        try:
            return extract_json(text)
        except LLMError:
            # one repair attempt at low temperature
            text = self.chat(system, user + "\n\nYour previous reply was not valid JSON. "
                             "Reply again with ONLY the JSON object.", 0.2, json_mode=True)
            return extract_json(text)


def _retry_after(err: urllib.error.HTTPError, body: str) -> float | None:
    """Seconds to wait from the Retry-After header or the 'try again in Xs' message."""
    try:
        h = err.headers.get("retry-after") if err.headers else None
        if h:
            return float(h)
    except (TypeError, ValueError):
        pass
    m = re.search(r"try again in (?:(\d+)m)?([\d.]+)(ms|s)", body)
    if m:
        mins = float(m.group(1) or 0)
        val = float(m.group(2))
        return mins * 60 + (val / 1000 if m.group(3) == "ms" else val)
    return None


def check(llm: "LLM | None" = None) -> bool:
    """One tiny test call. Usage: python -m levelforge.llm"""
    llm = llm or LLM()
    print(f"Provider: {llm.describe()}")
    if not llm.online:
        print("No API key found. Put GROQ_API_KEY=... in the .env file next to run_demo.py.")
        return False
    try:
        reply = llm.chat("You are a test endpoint.", "Reply with the single word: ready", temperature=0)
        print(f"OK - model replied: {reply.strip()[:60]!r}")
        return True
    except LLMError as e:
        print(f"FAILED - {e}")
        return False



def extract_json(text: str):
    """Pull the first JSON object/array out of a model reply."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                continue
    raise LLMError(f"could not parse JSON from reply: {text[:200]}")


if __name__ == "__main__":
    raise SystemExit(0 if check() else 1)
