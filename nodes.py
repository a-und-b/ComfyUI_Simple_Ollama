"""
ComfyUI_Simple_Ollama
=====================
A simple, robust custom node for talking to any Ollama server
(local or LAN) directly from your ComfyUI workflow.

Features
--------
- Dynamic model list via Connect button (JS extension)
- Model info display (parameters, quant, context window)
- Vision / image input (base64, works with any multimodal model)
- System prompt + combined prompt input
- Thinking mode (QwQ, DeepSeek-R1, …)
- Seed, max_tokens, temperature, keep_alive
- Separate "response", "thinking" and "prompt_sent" outputs
"""

import json
import base64
import io
import re
import urllib.request
import urllib.error

import numpy as np
from PIL import Image

# ---------------------------------------------------------------------------
# Helper: call Ollama from Python (used by both routes and node)
# ---------------------------------------------------------------------------

def _ollama_request(url: str, path: str, payload: dict | None = None,
                    method: str = "GET", timeout: int = 8) -> dict:
    """Small wrapper around urllib to call an Ollama API endpoint."""
    full_url = f"{url.rstrip('/')}{path}"
    data = json.dumps(payload).encode("utf-8") if payload else None
    req = urllib.request.Request(
        full_url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST" if data else method,
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


# ---------------------------------------------------------------------------
# Server-side routes (JS frontend → Python backend → Ollama)
# ---------------------------------------------------------------------------
try:
    from server import PromptServer
    from aiohttp import web

    @PromptServer.instance.routes.get("/simple_ollama/models")
    async def simple_ollama_list_models(request):
        """Return the list of available model names on the Ollama server."""
        url = request.query.get("url", "http://localhost:11434")
        try:
            data = _ollama_request(url, "/api/tags")
            models = sorted(m["name"] for m in data.get("models", []))
            return web.json_response({"success": True, "models": models})
        except Exception as exc:
            return web.json_response(
                {"success": False, "models": [], "error": str(exc)},
                status=200,
            )

    @PromptServer.instance.routes.get("/simple_ollama/model_info")
    async def simple_ollama_model_info(request):
        """Return metadata for a specific model (context window, params, quant)."""
        url   = request.query.get("url", "http://localhost:11434")
        model = request.query.get("model", "")
        if not model:
            return web.json_response({"success": False, "error": "No model specified"})
        try:
            data = _ollama_request(url, "/api/show", {"model": model})

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
        except Exception as exc:
            return web.json_response(
                {"success": False, "error": str(exc)},
                status=200,
            )

except ImportError:
    pass


# ---------------------------------------------------------------------------
# The node itself
# ---------------------------------------------------------------------------
class SimpleOllamaNode:
    """Send a prompt (+ optional image) to an Ollama server and return the
    model's response plus its reasoning/thinking trace."""

    CATEGORY = "AI/Ollama"
    FUNCTION = "run"
    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("response", "thinking", "prompt_sent")

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
                    "tooltip": "Random seed for reproducible outputs. 0 = random each run.",
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
                    "tooltip": "Minutes to keep model loaded in VRAM after the request. -1 = forever, 0 = unload immediately.",
                }),
                "thinking_mode": ("BOOLEAN", {
                    "default": False,
                    "label_on": "Thinking ON",
                    "label_off": "Thinking OFF",
                    "tooltip": "Enable extended thinking/reasoning (requires a supporting model, e.g. QwQ, DeepSeek-R1).",
                }),
            },
            "optional": {
                # --- Vision ---
                "image": ("IMAGE", {
                    "tooltip": "Optional image input. Connect any IMAGE node here. Only the first frame is used.",
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
    def VALIDATE_INPUTS(cls, model, **_kwargs):
        """The model COMBO is populated dynamically by the JS extension after
        connecting to Ollama — accept any non-empty string so ComfyUI doesn't
        reject values that aren't in the static ['none'] list."""
        if not model or model == "none":
            return "Select a model first (click 🔌 Connect to load the list)."
        return True

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
        image=None,
        system_prompt: str = "",
    ):
        url = ollama_url.rstrip("/")

        # ---- Build the message list ----------------------------------
        messages = []

        if system_prompt and system_prompt.strip():
            messages.append({"role": "system", "content": system_prompt.strip()})

        user_msg: dict = {"role": "user", "content": prompt}

        # Vision: attach image as base64
        if image is not None:
            user_msg["images"] = [self._tensor_to_base64(image)]

        messages.append(user_msg)

        # ---- Build the request payload --------------------------------
        # keep_alive: Ollama expects a duration string like "5m", "0", "-1"
        if keep_alive < 0:
            keep_alive_str = "-1m"
        elif keep_alive == 0:
            keep_alive_str = "0m"
        else:
            keep_alive_str = f"{keep_alive}m"

        payload: dict = {
            "model": model,
            "messages": messages,
            "stream": False,
            "keep_alive": keep_alive_str,
            "options": {
                "seed": seed,
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }

        # Explicitly send think: true/false — models like Qwen 3 think by
        # default, consuming the entire num_predict budget on reasoning tokens
        # and returning empty content unless explicitly told not to.
        payload["think"] = thinking_mode

        # ---- Call the Ollama API -------------------------------------
        raw = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{url}/api/chat",
            data=raw,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                result = json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")
            raise RuntimeError(
                f"[SimpleOllama] Ollama returned HTTP {exc.code}: {body}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"[SimpleOllama] Cannot reach Ollama at '{url}': {exc.reason}"
            ) from exc

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
    def _tensor_to_base64(image_tensor) -> str:
        """Convert a ComfyUI IMAGE tensor (B,H,W,C float32 0-1) to a
        PNG base64 string that Ollama's API accepts."""
        frame = image_tensor[0]
        arr = (frame.cpu().numpy() * 255).clip(0, 255).astype(np.uint8)
        pil = Image.fromarray(arr)
        buf = io.BytesIO()
        pil.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("utf-8")


# ---------------------------------------------------------------------------
# Node registration
# ---------------------------------------------------------------------------
NODE_CLASS_MAPPINGS = {
    "SimpleOllamaNode": SimpleOllamaNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SimpleOllamaNode": "Simple Ollama 🦙",
}
