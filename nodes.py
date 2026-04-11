"""
ComfyUI_Simple_Ollama
=====================
A simple, robust custom node for talking to any Ollama server
(local or LAN) directly from your ComfyUI workflow.

Features
--------
- Dynamic model list via Connect button (JS extension)
- Model info display (parameters, quant, context window)
- Vision / image input (single image or IMAGE batches)
- System prompt + combined prompt input
- Thinking mode (QwQ, DeepSeek-R1, ...)
- Seed, max_tokens, temperature, keep_alive
- Separate "response", "thinking" and "prompt_text" outputs
"""

import base64
import hashlib
import io
import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
import asyncio

import numpy as np
from PIL import Image

# ---------------------------------------------------------------------------
# Helper: call Ollama from Python (used by both routes and node)
# ---------------------------------------------------------------------------

class OllamaRequestError(RuntimeError):
    """Raised when an upstream Ollama request fails."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def _normalize_ollama_url(url: str) -> str:
    """Validate and normalize the Ollama base URL."""
    candidate = (url or "").strip()
    if not candidate:
        raise ValueError("Enter an Ollama URL first.")

    parsed = urllib.parse.urlsplit(candidate)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Ollama URL must start with http:// or https://")
    if not parsed.netloc:
        raise ValueError("Ollama URL must include a host.")
    if parsed.query or parsed.fragment:
        raise ValueError("Ollama URL must not include query parameters or fragments.")

    normalized_path = parsed.path.rstrip("/")
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, normalized_path, "", "")
    )


def _resolve_effective_ollama_url(ollama_url: str, ollama_url_override: str = "") -> str:
    """Use the override URL when provided, otherwise fall back to the widget URL."""
    override = (ollama_url_override or "").strip()
    primary = (ollama_url or "").strip()
    effective_url = override or primary
    return _normalize_ollama_url(effective_url)


def _ollama_request(url: str, path: str, payload: dict | None = None,
                    method: str = "GET", timeout: int = 8) -> dict:
    """Small wrapper around urllib to call an Ollama API endpoint."""
    normalized_url = _normalize_ollama_url(url)
    full_url = f"{normalized_url.rstrip('/')}{path}"
    data = json.dumps(payload).encode("utf-8") if payload else None
    req = urllib.request.Request(
        full_url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST" if data else method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            return json.loads(resp.read().decode(charset))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace").strip()
        detail = body or exc.reason or "Upstream HTTP error"
        raise OllamaRequestError(
            f"Ollama returned HTTP {exc.code}: {detail}",
            status_code=502,
        ) from exc
    except urllib.error.URLError as exc:
        reason = exc.reason
        reason_text = getattr(reason, "strerror", None) or str(reason)
        status_code = 504 if isinstance(reason, socket.timeout) else 502
        raise OllamaRequestError(
            f"Cannot reach Ollama at '{normalized_url}': {reason_text}",
            status_code=status_code,
        ) from exc


async def _ollama_request_async(url: str, path: str, payload: dict | None = None,
                                method: str = "GET", timeout: int = 8) -> dict:
    """Run the blocking urllib request outside ComfyUI's aiohttp event loop."""
    return await asyncio.to_thread(_ollama_request, url, path, payload, method, timeout)


# ---------------------------------------------------------------------------
# Server-side routes (JS frontend → Python backend → Ollama)
# ---------------------------------------------------------------------------
try:
    from server import PromptServer
    from aiohttp import web

    def _json_error(message: str, status: int, **extra):
        payload = {"success": False, "error": message}
        payload.update(extra)
        return web.json_response(payload, status=status)

    @PromptServer.instance.routes.get("/simple_ollama/models")
    async def simple_ollama_list_models(request):
        """Return the list of available model names on the Ollama server."""
        # This route proxies to a user-supplied Ollama URL, so it is intended
        # for trusted/local ComfyUI deployments.
        url = request.query.get("url", "http://localhost:11434")
        try:
            data = await _ollama_request_async(url, "/api/tags")
            models = sorted(m["name"] for m in data.get("models", []))
            return web.json_response({"success": True, "models": models})
        except ValueError as exc:
            return _json_error(str(exc), status=400, models=[])
        except OllamaRequestError as exc:
            return _json_error(str(exc), status=exc.status_code, models=[])

    @PromptServer.instance.routes.get("/simple_ollama/model_info")
    async def simple_ollama_model_info(request):
        """Return metadata for a specific model (context window, params, quant)."""
        url   = request.query.get("url", "http://localhost:11434")
        model = request.query.get("model", "")
        if not model:
            return _json_error("No model specified", status=400)
        try:
            data = await _ollama_request_async(url, "/api/show", {"model": model})

            details = data.get("details", {})
            model_info = data.get("model_info", {})

            # --- Extract useful fields ---
            family          = details.get("family", "?")
            parameter_size  = details.get("parameter_size", "?")
            quant_level     = details.get("quantization_level", "?")

            # Context length lives in model_info under various keys
            ctx_length = None
            for key in model_info:
                if "context_length" in key:
                    ctx_length = model_info[key]
                    break

            # Fallback: parse from the parameters string
            if ctx_length is None:
                params_str = data.get("parameters", "")
                for line in params_str.splitlines():
                    if "num_ctx" in line:
                        parts = line.split()
                        if len(parts) >= 2:
                            try:
                                ctx_length = int(parts[-1])
                            except ValueError:
                                pass

            return web.json_response({
                "success": True,
                "family": family,
                "parameter_size": parameter_size,
                "quantization": quant_level,
                "context_length": ctx_length,
            })
        except ValueError as exc:
            return _json_error(str(exc), status=400)
        except OllamaRequestError as exc:
            return _json_error(str(exc), status=exc.status_code)

except ImportError:
    pass


# ---------------------------------------------------------------------------
# The node itself
# ---------------------------------------------------------------------------
class SimpleOllamaConnectionNode:
    """Provide a shared Ollama URL for multiple Simple Ollama nodes."""

    CATEGORY = "AI/Ollama"
    FUNCTION = "run"
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("ollama_url",)

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "ollama_url": ("STRING", {
                    "default": "http://192.168.1.x:11434",
                    "multiline": False,
                    "tooltip": "Shared Ollama base URL for downstream Simple Ollama nodes.",
                }),
            },
        }

    @classmethod
    def VALIDATE_INPUTS(cls, ollama_url, **_kwargs):
        try:
            _normalize_ollama_url(ollama_url)
        except ValueError as exc:
            return str(exc)
        return True

    def run(self, ollama_url: str):
        return (_normalize_ollama_url(ollama_url),)


class SimpleOllamaNode:
    """Send a prompt (+ optional image) to an Ollama server and return the
    model's response plus its reasoning/thinking trace."""

    CATEGORY = "AI/Ollama"
    FUNCTION = "run"
    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("response", "thinking", "prompt_text")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                # --- Connection ---
                "ollama_url": ("STRING", {
                    "default": "http://192.168.1.x:11434",
                    "multiline": False,
                    "tooltip": "Base URL of your Ollama server. Click 'Connect' to load models.",
                }),
                # Starts as a one-item combo; JS replaces the list after Connect
                "model": (["none"], {
                    "tooltip": "Click '🔌 Connect' first to populate this list.",
                }),

                # --- Prompt ---
                "prompt": ("STRING", {
                    "default": "",
                    "multiline": True,
                    "placeholder": "Paste any context, documents or instructions here, then ask your question.",
                    "tooltip": "Everything the model sees as the user turn — context and question in one field.",
                }),

                # --- Generation options ---
                "seed": ("INT", {
                    "default": 0,
                    "min": 0,
                    "max": 0xFFFFFFFFFFFFFFFF,
                    "tooltip": "Random seed for reproducible outputs.",
                }),
                "max_tokens": ("INT", {
                    "default": 1024,
                    "min": 1,
                    "max": 131072,
                    "step": 64,
                    "tooltip": "Maximum number of tokens the model may generate (num_predict).",
                }),
                "temperature": ("FLOAT", {
                    "default": 0.7,
                    "min": 0.0,
                    "max": 2.0,
                    "step": 0.05,
                    "round": 0.01,
                    "tooltip": "Sampling temperature. Lower = more deterministic.",
                }),
                "keep_alive": ("FLOAT", {
                    "default": 5.0,
                    "min": -1.0,
                    "max": 1440.0,
                    "step": 1.0,
                    "round": 0.1,
                    "tooltip": "Minutes to keep the model loaded after the request. -1 = keep loaded, 0 = unload immediately.",
                }),
                "thinking_mode": ("BOOLEAN", {
                    "default": False,
                    "label_on": "Thinking ON",
                    "label_off": "Thinking OFF",
                    "tooltip": "Enable extended thinking/reasoning (requires a supporting model, e.g. QwQ, DeepSeek-R1).",
                }),
            },
            "optional": {
                "ollama_url_override": ("STRING", {
                    "forceInput": True,
                    "tooltip": "Optional shared Ollama URL input, for example from the Ollama Connection node.",
                }),
                # --- Vision ---
                "image": ("IMAGE", {
                    "tooltip": "Optional vision input. A single image sends one image; an IMAGE batch sends all frames.",
                }),
                # --- System prompt ---
                "system_prompt": ("STRING", {
                    "default": "",
                    "multiline": True,
                    "placeholder": "You are a helpful assistant…",
                    "tooltip": "System-level instruction prepended before the conversation.",
                }),
            },
        }

    @classmethod
    def VALIDATE_INPUTS(cls, model, ollama_url="", ollama_url_override="", **_kwargs):
        """The model COMBO is populated dynamically by the JS extension after
        connecting to Ollama — accept any non-empty string so ComfyUI doesn't
        reject values that aren't in the static ['none'] list."""
        if not model or model == "none":
            return "Select a model first (click 🔌 Connect to load the list)."
        try:
            _resolve_effective_ollama_url(ollama_url, ollama_url_override)
        except ValueError as exc:
            return str(exc)
        return True

    @classmethod
    def IS_CHANGED(
        cls,
        ollama_url: str,
        model: str,
        prompt: str,
        seed: int,
        max_tokens: int,
        temperature: float,
        keep_alive: float,
        thinking_mode: bool,
        ollama_url_override: str = "",
        image=None,
        system_prompt: str = "",
    ):
        try:
            normalized_url = _resolve_effective_ollama_url(
                ollama_url,
                ollama_url_override,
            )
        except ValueError:
            normalized_url = ((ollama_url_override or "").strip() or (ollama_url or "").strip())

        return (
            normalized_url,
            model,
            prompt,
            seed,
            max_tokens,
            temperature,
            keep_alive,
            thinking_mode,
            system_prompt,
            cls._image_fingerprint(image),
        )

    # ------------------------------------------------------------------
    def run(
        self,
        ollama_url: str,
        model: str,
        prompt: str,
        seed: int,
        max_tokens: int,
        temperature: float,
        keep_alive: float,
        thinking_mode: bool,
        ollama_url_override: str = "",
        image=None,
        system_prompt: str = "",
    ):
        url = _resolve_effective_ollama_url(ollama_url, ollama_url_override)

        # ---- Build the message list ----------------------------------
        messages = []

        if system_prompt and system_prompt.strip():
            messages.append({"role": "system", "content": system_prompt.strip()})

        user_msg: dict = {"role": "user", "content": prompt}

        # Vision: attach image as base64
        if image is not None:
            encoded_images = self._image_tensor_to_base64_strings(image)
            if encoded_images:
                user_msg["images"] = encoded_images

        messages.append(user_msg)

        # ---- Build the request payload --------------------------------
        keep_alive_value = self._format_keep_alive(keep_alive)
        options = {
            "seed": seed,
            "num_predict": max_tokens,
            "temperature": temperature,
        }

        payload: dict = {
            "model": model,
            "messages": messages,
            "stream": False,
            "keep_alive": keep_alive_value,
            "options": options,
        }

        # Explicitly send think: true/false — models like Qwen 3 think by
        # default, consuming the entire num_predict budget on reasoning tokens
        # and returning empty content unless explicitly told not to.
        payload["think"] = thinking_mode

        try:
            result = _ollama_request(url, "/api/chat", payload, method="POST", timeout=600)
        except (ValueError, OllamaRequestError) as exc:
            raise RuntimeError(f"[SimpleOllama] {exc}") from exc

        message = result.get("message", {})
        response_text: str = message.get("content", "")
        thinking_text: str = message.get("thinking", "")

        # Some models (DeepSeek-R1, older Qwen) embed <think>…</think> tags
        # directly inside content instead of using the separate thinking field.
        # Strip them out so the response output is always clean.
        think_pattern = re.compile(r"<think>(.*?)</think>", re.DOTALL)
        inline_think = think_pattern.findall(response_text)
        if inline_think:
            if not thinking_text:
                thinking_text = "\n\n".join(inline_think)
            response_text = think_pattern.sub("", response_text).strip()

        # Log a short summary to the ComfyUI console
        tok_in  = result.get("prompt_eval_count", "?")
        tok_out = result.get("eval_count", "?")
        dur     = result.get("total_duration")
        dur_s   = f"{dur / 1e9:.1f}s" if isinstance(dur, (int, float)) else "?"
        print(
            f"[SimpleOllama] model={model}  "
            f"tokens in={tok_in} out={tok_out}  "
            f"time={dur_s}  "
            f"thinking={'yes' if thinking_text else 'no'}"
        )

        return (response_text, thinking_text, prompt)

    # ------------------------------------------------------------------
    @staticmethod
    def _format_keep_alive(keep_alive: float):
        """Return a documented Ollama keep_alive value."""
        if keep_alive < 0:
            return -1
        if keep_alive == 0:
            return 0
        return f"{keep_alive:g}m"

    @staticmethod
    def _image_tensor_to_numpy(image_tensor) -> np.ndarray:
        """Convert IMAGE input data into a numpy array."""
        if hasattr(image_tensor, "cpu"):
            array = image_tensor.cpu().numpy()
        elif hasattr(image_tensor, "numpy"):
            array = image_tensor.numpy()
        else:
            array = np.asarray(image_tensor)
        return np.asarray(array)

    @classmethod
    def _image_tensor_to_base64_strings(cls, image_tensor) -> list[str]:
        """Convert a ComfyUI IMAGE tensor into one or more base64 PNG strings."""
        image_array = cls._image_tensor_to_numpy(image_tensor)
        if image_array.ndim == 3:
            frames = image_array[np.newaxis, ...]
        elif image_array.ndim == 4:
            frames = image_array
        else:
            raise RuntimeError(
                f"[SimpleOllama] Unsupported IMAGE tensor shape: {image_array.shape}"
            )

        encoded_images = []
        for frame in frames:
            arr = (frame * 255).clip(0, 255).astype(np.uint8)
            pil = Image.fromarray(arr)
            buf = io.BytesIO()
            pil.save(buf, format="PNG")
            encoded_images.append(base64.b64encode(buf.getvalue()).decode("utf-8"))
        return encoded_images

    @classmethod
    def _image_fingerprint(cls, image_tensor):
        """Hash IMAGE contents so ComfyUI invalidates cache on image changes."""
        if image_tensor is None:
            return None

        image_array = np.ascontiguousarray(cls._image_tensor_to_numpy(image_tensor))
        hasher = hashlib.sha256()
        hasher.update(str(image_array.shape).encode("utf-8"))
        hasher.update(image_array.dtype.str.encode("utf-8"))
        hasher.update(image_array.tobytes())
        return hasher.hexdigest()


# ---------------------------------------------------------------------------
# Node registration
# ---------------------------------------------------------------------------
NODE_CLASS_MAPPINGS = {
    "SimpleOllamaConnectionNode": SimpleOllamaConnectionNode,
    "SimpleOllamaNode": SimpleOllamaNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SimpleOllamaConnectionNode": "Ollama Connection",
    "SimpleOllamaNode": "Simple Ollama 🦙",
}
