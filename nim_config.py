"""One place for the model server settings.

Every file that talks to the model (app.py, vision/compliance_checker.py,
vision/nim_vision_client.py) reads its URL and model name from here, so
switching models means editing config_nim.yaml only.

Environment variables override the file, which is handy for quick tests:
    NIM_URL=http://192.168.0.50:8000/v1/chat/completions python3 app.py
    NIM_MODEL=qwen python3 app.py
"""

import os
import re

_DEFAULTS = {
    "base_url": "http://localhost:8000/v1/chat/completions",
    "model": "qwen",
}

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config_nim.yaml")


def _load_file():
    """Read config_nim.yaml. Uses PyYAML if installed, else a tiny parser."""
    if not os.path.exists(_CONFIG_PATH):
        return {}
    try:
        import yaml
        with open(_CONFIG_PATH) as f:
            data = yaml.safe_load(f) or {}
        return data.get("nim", {}) or {}
    except ImportError:
        values = {}
        with open(_CONFIG_PATH) as f:
            for line in f:
                line = line.split("#", 1)[0].strip()
                if ":" in line and not line.endswith(":"):
                    key, value = line.split(":", 1)
                    values[key.strip()] = value.strip().strip('"').strip("'")
        return values


_file = _load_file()

NIM_URL = os.environ.get("NIM_URL") or _file.get("base_url") or _DEFAULTS["base_url"]
NIM_MODEL = os.environ.get("NIM_MODEL") or _file.get("model") or _DEFAULTS["model"]
NIM_API_KEY = os.environ.get("NIM_API_KEY") or None

# Folder of the Qwen one-click kit (has linux/start.sh); lets the UI start/stop it.
NIM_SERVER_DIR = os.path.expanduser(
    os.environ.get("NIM_SERVER_DIR") or _file.get("server_dir") or "")

# Qwen-style "thinking" models can spend hundreds of tokens reasoning before
# they answer. For short YES/NO checks and JSON plans that is slow and can run
# out of max_tokens before the answer appears, so it is switched off by default.
# Set  disable_thinking: false  in config_nim.yaml to turn thinking back on.
_dt = os.environ.get("NIM_DISABLE_THINKING", str(_file.get("disable_thinking", "true")))
DISABLE_THINKING = str(_dt).strip().lower() not in ("false", "0", "no")


def extra_params():
    """Extra request fields to merge into every chat-completion payload."""
    if DISABLE_THINKING:
        # vLLM passes this to the model's chat template (Qwen3-style switch).
        # Templates that don't use it simply ignore it.
        return {"chat_template_kwargs": {"enable_thinking": False}}
    return {}


def headers():
    """HTTP headers for the model server (adds the API key only if one is set)."""
    h = {"Content-Type": "application/json"}
    if NIM_API_KEY:
        h["Authorization"] = f"Bearer {NIM_API_KEY}"
    return h


_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def extract_answer(message):
    """Return the model's final answer text from a chat-completion message.

    Works for both models:
    - Qwen (and most models): the answer is in "content". If the server was
      started without a reasoning parser, the thinking arrives inline as
      <think>...</think> before the answer, so it is stripped here.
    - Nemotron NIM: sometimes puts everything in "reasoning" and leaves
      "content" empty, so that is used as a fallback.
    """
    content = message.get("content") or ""
    if "</think>" in content.lower():
        content = _THINK_RE.sub("", content)
        # unterminated or leading-only think block: keep what follows </think>
        if "</think>" in content.lower():
            content = re.split(r"</think>", content, flags=re.IGNORECASE)[-1]
    content = content.strip()
    if content:
        return content
    return (message.get("reasoning") or message.get("reasoning_content") or "").strip()