"""
Ollama HTTP Client
==================
Thin wrapper around the Ollama REST API.  All AI inference in LegalLens-AI
goes through this module instead of the Google Gemini SDK.

Endpoints used:
  POST /api/generate   – single-turn completion (used by agents)
  POST /api/chat       – multi-turn chat (used by the chatbot)
  GET  /api/tags       – list available models (used for health check)
"""

import json
import requests
from typing import Generator, Optional

from .config import OLLAMA_BASE_URL, OLLAMA_MODEL, OLLAMA_TIMEOUT


# ---------------------------------------------------------------------------
# Helper – connectivity & model validation
# ---------------------------------------------------------------------------

def check_ollama_health() -> dict:
    """
    Verify that Ollama is reachable and that the configured model is present.

    Returns a dict with keys:
      ok      (bool)  – True if everything is ready
      error   (str)   – human-readable problem description, or ""
      hint    (str)   – actionable fix suggestion, or ""
    """
    try:
        resp = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        resp.raise_for_status()
    except requests.exceptions.ConnectionError:
        return {
            "ok": False,
            "error": f"Cannot connect to Ollama at {OLLAMA_BASE_URL}.",
            "hint": (
                "Make sure Ollama is installed and running.\n"
                "  • Install: https://ollama.com/download\n"
                "  • Start:   ollama serve\n"
                f"  • Then:    ollama pull {OLLAMA_MODEL}"
            ),
        }
    except requests.exceptions.Timeout:
        return {
            "ok": False,
            "error": "Ollama did not respond within 5 seconds.",
            "hint": "Check that the Ollama service is not overloaded or crashed.",
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": f"Unexpected error contacting Ollama: {exc}",
            "hint": "Restart Ollama and try again.",
        }

    # Check that the model exists locally
    available = [m.get("name", "") for m in resp.json().get("models", [])]
    if not any(OLLAMA_MODEL in name for name in available):
        return {
            "ok": False,
            "error": f"Model '{OLLAMA_MODEL}' is not downloaded.",
            "hint": (
                f"Run the following command to download it:\n"
                f"  ollama pull {OLLAMA_MODEL}\n\n"
                f"Available models: {', '.join(available) or 'none'}"
            ),
        }

    return {"ok": True, "error": "", "hint": ""}


# ---------------------------------------------------------------------------
# Core: single-turn generation (used by agent pipeline)
# ---------------------------------------------------------------------------

def generate(
    prompt: str,
    system: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.1,
    timeout: Optional[int] = None,
) -> str:
    """
    Send a single prompt to Ollama and return the full response text.

    Args:
        prompt:      The user message / instruction.
        system:      Optional system prompt prepended to the conversation.
        model:       Model tag override; defaults to OLLAMA_MODEL.
        temperature: Sampling temperature (lower = more deterministic JSON).
        timeout:     Request timeout in seconds; defaults to OLLAMA_TIMEOUT.

    Returns:
        The model's response as a plain string.

    Raises:
        RuntimeError with a descriptive message on failure.
    """
    _model = model or OLLAMA_MODEL
    _timeout = timeout or OLLAMA_TIMEOUT

    payload: dict = {
        "model": _model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": 4096,
            "num_ctx": 4096,
        },
    }
    if system:
        payload["system"] = system

    try:
        resp = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json=payload,
            timeout=_timeout,
        )
        resp.raise_for_status()
        return resp.json().get("response", "")
    except requests.exceptions.ConnectionError:
        raise RuntimeError(
            f"Cannot connect to Ollama at {OLLAMA_BASE_URL}. "
            "Is the service running? Try: ollama serve"
        )
    except requests.exceptions.Timeout:
        raise RuntimeError(
            f"Ollama request timed out after {_timeout}s. "
            "The model may be loading – wait a moment and retry."
        )
    except requests.exceptions.HTTPError as exc:
        raise RuntimeError(f"Ollama HTTP error: {exc}\nResponse: {resp.text}")
    except Exception as exc:
        raise RuntimeError(f"Ollama generate failed: {exc}")


# ---------------------------------------------------------------------------
# Core: single-turn streaming generation (used for long outputs like reports)
# ---------------------------------------------------------------------------

def generate_stream(
    prompt: str,
    system: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.1,
    token_timeout: int = 60,
) -> Generator[str, None, None]:
    """
    Send a prompt to Ollama and stream back tokens as they are generated.

    Unlike generate(), this never hits a hard wall-clock timeout because
    the connection stays alive and receives data continuously.  A per-token
    timeout (token_timeout) is applied so a completely frozen model is still
    detected.

    Args:
        prompt:        The user prompt.
        system:        Optional system message.
        model:         Model tag override; defaults to OLLAMA_MODEL.
        temperature:   Sampling temperature.
        token_timeout: Max seconds to wait between individual tokens (not total).

    Yields:
        Incremental text tokens from the model.

    Raises:
        RuntimeError on connection or HTTP errors.
    """
    _model = model or OLLAMA_MODEL

    payload: dict = {
        "model": _model,
        "prompt": prompt,
        "stream": True,
        "options": {
            "temperature": temperature,
            "num_predict": 2048,
            "num_ctx": 4096,
        },
    }
    if system:
        payload["system"] = system

    try:
        with requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json=payload,
            stream=True,
            timeout=token_timeout,  # per-chunk timeout, not total
        ) as resp:
            resp.raise_for_status()
            for raw_line in resp.iter_lines():
                if raw_line:
                    try:
                        chunk = json.loads(raw_line)
                        token = chunk.get("response", "")
                        if token:
                            yield token
                        if chunk.get("done", False):
                            break
                    except json.JSONDecodeError:
                        continue
    except requests.exceptions.ConnectionError:
        raise RuntimeError(
            f"Cannot connect to Ollama at {OLLAMA_BASE_URL}. "
            "Is the service running? Try: ollama serve"
        )
    except requests.exceptions.Timeout:
        raise RuntimeError(
            "Ollama stopped responding between tokens. "
            "The model may be overloaded — try again or switch to a smaller model."
        )
    except requests.exceptions.HTTPError as exc:
        raise RuntimeError(f"Ollama HTTP error during streaming: {exc}")
    except Exception as exc:
        raise RuntimeError(f"Ollama stream failed: {exc}")


def generate_stream_collect(
    prompt: str,
    system: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.1,
    token_timeout: int = 60,
    print_progress: bool = False,
) -> str:
    """
    Convenience wrapper: stream and collect all tokens into a single string.
    Optionally print a dot every 10 tokens to show progress.
    """
    parts: list[str] = []
    count = 0
    for token in generate_stream(
        prompt,
        system=system,
        model=model,
        temperature=temperature,
        token_timeout=token_timeout,
    ):
        parts.append(token)
        count += 1
        if print_progress and count % 30 == 0:
            print(".", end="", flush=True)
    if print_progress and count > 0:
        print(f" ({count} tokens)", flush=True)
    return "".join(parts)


# ---------------------------------------------------------------------------
# Core: multi-turn chat with streaming (used by the chatbot)
# ---------------------------------------------------------------------------

def chat_stream(
    messages: list[dict],
    model: Optional[str] = None,
    temperature: float = 0.2,
    timeout: Optional[int] = None,
) -> Generator[str, None, None]:
    """
    Send a list of chat messages to Ollama and stream the response tokens.

    Args:
        messages:    OpenAI-style list of {"role": ..., "content": ...}.
        model:       Model tag override; defaults to OLLAMA_MODEL.
        temperature: Sampling temperature.
        timeout:     Request timeout in seconds.

    Yields:
        Incremental text chunks from the model response.

    Raises:
        RuntimeError on connection or HTTP errors.
    """
    _model = model or OLLAMA_MODEL
    _timeout = timeout or OLLAMA_TIMEOUT

    payload = {
        "model": _model,
        "messages": messages,
        "stream": True,
        "options": {
            "temperature": temperature,
            "num_predict": 2048,
            "num_ctx": 4096,
        },
    }

    try:
        with requests.post(
            f"{OLLAMA_BASE_URL}/api/chat",
            json=payload,
            stream=True,
            timeout=_timeout,
        ) as resp:
            resp.raise_for_status()
            for raw_line in resp.iter_lines():
                if raw_line:
                    try:
                        chunk = json.loads(raw_line)
                        token = chunk.get("message", {}).get("content", "")
                        if token:
                            yield token
                        if chunk.get("done", False):
                            break
                    except json.JSONDecodeError:
                        continue  # skip malformed lines
    except requests.exceptions.ConnectionError:
        raise RuntimeError(
            f"Cannot connect to Ollama at {OLLAMA_BASE_URL}. "
            "Is the service running? Try: ollama serve"
        )
    except requests.exceptions.Timeout:
        raise RuntimeError(
            f"Ollama chat stream timed out after {_timeout}s."
        )
    except requests.exceptions.HTTPError as exc:
        raise RuntimeError(f"Ollama HTTP error during chat: {exc}")
    except Exception as exc:
        raise RuntimeError(f"Ollama chat stream failed: {exc}")


# ---------------------------------------------------------------------------
# Helper: extract JSON from model output reliably
# ---------------------------------------------------------------------------

def extract_json(text: str) -> dict:
    """
    Try to parse a JSON object out of a model response that may contain
    surrounding markdown fences or prose.

    Returns the parsed dict, or {"raw": text} on failure.
    """
    # Strip markdown code fences
    cleaned = text.strip()
    for fence in ("```json", "```JSON", "```"):
        if cleaned.startswith(fence):
            cleaned = cleaned[len(fence):]
            break
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    # Try direct parse first
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Try to find the first { ... } or [ ... ] block
    for start_char, end_char in [('{', '}'), ('[', ']')]:
        start = cleaned.find(start_char)
        end = cleaned.rfind(end_char)
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(cleaned[start:end + 1])
            except json.JSONDecodeError:
                pass

    # Give up – return raw text so callers can surface it
    return {"raw": text, "parse_error": True}
