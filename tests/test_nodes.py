"""Unit tests for the pure-Python logic in ComfyUI_Simple_Ollama.

These exercise the parts that don't need a live Ollama server: URL
normalization + the SSRF host allowlist, the override-resolution precedence,
keep_alive formatting, the inline <think> stripping, and image encoding.
"""

import base64
import io

import numpy as np
import pytest
from PIL import Image

import nodes


# ---------------------------------------------------------------------------
# _normalize_ollama_url
# ---------------------------------------------------------------------------
class TestNormalizeUrl:
    def test_strips_trailing_slash(self):
        assert nodes._normalize_ollama_url("http://localhost:11434/") == "http://localhost:11434"

    def test_keeps_host_and_port(self):
        assert nodes._normalize_ollama_url("http://192.168.1.5:11434") == "http://192.168.1.5:11434"

    def test_https_allowed(self):
        assert nodes._normalize_ollama_url("https://ollama.example.com") == "https://ollama.example.com"

    def test_empty_rejected(self):
        with pytest.raises(ValueError):
            nodes._normalize_ollama_url("")

    def test_missing_scheme_rejected(self):
        with pytest.raises(ValueError):
            nodes._normalize_ollama_url("localhost:11434")

    def test_non_http_scheme_rejected(self):
        with pytest.raises(ValueError):
            nodes._normalize_ollama_url("ftp://localhost:11434")

    def test_missing_host_rejected(self):
        with pytest.raises(ValueError):
            nodes._normalize_ollama_url("http://")

    def test_query_rejected(self):
        with pytest.raises(ValueError):
            nodes._normalize_ollama_url("http://localhost:11434?x=1")

    def test_fragment_rejected(self):
        with pytest.raises(ValueError):
            nodes._normalize_ollama_url("http://localhost:11434#frag")


# ---------------------------------------------------------------------------
# Host allowlist (SSRF hardening)
# ---------------------------------------------------------------------------
class TestAllowlist:
    def test_no_env_allows_any_host(self, monkeypatch):
        monkeypatch.delenv(nodes.ALLOWLIST_ENV_VAR, raising=False)
        assert nodes._normalize_ollama_url("http://10.0.0.9:11434") == "http://10.0.0.9:11434"

    def test_host_on_allowlist_passes(self, monkeypatch):
        monkeypatch.setenv(nodes.ALLOWLIST_ENV_VAR, "localhost, 192.168.1.5")
        assert nodes._normalize_ollama_url("http://192.168.1.5:11434") == "http://192.168.1.5:11434"

    def test_host_off_allowlist_rejected(self, monkeypatch):
        monkeypatch.setenv(nodes.ALLOWLIST_ENV_VAR, "localhost")
        with pytest.raises(ValueError) as exc:
            nodes._normalize_ollama_url("http://169.254.169.254")
        assert "not allowed" in str(exc.value)

    def test_allowlist_is_case_insensitive(self, monkeypatch):
        monkeypatch.setenv(nodes.ALLOWLIST_ENV_VAR, "Ollama.Example.COM")
        assert nodes._normalize_ollama_url("https://ollama.example.com") == "https://ollama.example.com"

    def test_empty_env_treated_as_unset(self, monkeypatch):
        monkeypatch.setenv(nodes.ALLOWLIST_ENV_VAR, "   ")
        # whitespace-only -> no allowlist -> any host allowed
        assert nodes._normalize_ollama_url("http://10.1.2.3") == "http://10.1.2.3"


# ---------------------------------------------------------------------------
# _resolve_effective_ollama_url
# ---------------------------------------------------------------------------
class TestResolveEffectiveUrl:
    def test_override_takes_precedence(self):
        result = nodes._resolve_effective_ollama_url(
            "http://localhost:11434", "http://192.168.1.9:11434"
        )
        assert result == "http://192.168.1.9:11434"

    def test_falls_back_to_primary_when_no_override(self):
        assert nodes._resolve_effective_ollama_url("http://localhost:11434", "") == "http://localhost:11434"

    def test_blank_override_is_ignored(self):
        assert nodes._resolve_effective_ollama_url("http://localhost:11434", "   ") == "http://localhost:11434"


# ---------------------------------------------------------------------------
# _format_keep_alive
# ---------------------------------------------------------------------------
class TestKeepAlive:
    def test_negative_keeps_loaded(self):
        assert nodes.SimpleOllamaNode._format_keep_alive(-1.0) == -1

    def test_zero_unloads(self):
        assert nodes.SimpleOllamaNode._format_keep_alive(0.0) == 0

    def test_positive_formats_minutes(self):
        assert nodes.SimpleOllamaNode._format_keep_alive(5.0) == "5m"

    def test_fractional_minutes(self):
        assert nodes.SimpleOllamaNode._format_keep_alive(2.5) == "2.5m"


# ---------------------------------------------------------------------------
# Inline <think> stripping (regex used inside run())
# ---------------------------------------------------------------------------
class TestInlineThinkRegex:
    def test_extracts_and_strips(self):
        import re

        pattern = re.compile(r"<think>(.*?)</think>", re.DOTALL)
        text = "<think>reasoning here</think>Final answer."
        found = pattern.findall(text)
        cleaned = pattern.sub("", text).strip()
        assert found == ["reasoning here"]
        assert cleaned == "Final answer."

    def test_no_tags_leaves_text_untouched(self):
        import re

        pattern = re.compile(r"<think>(.*?)</think>", re.DOTALL)
        text = "Just a plain answer."
        assert pattern.findall(text) == []
        assert pattern.sub("", text).strip() == "Just a plain answer."


# ---------------------------------------------------------------------------
# Image encoding
# ---------------------------------------------------------------------------
def _decode_png(b64: str) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(b64)))


class TestImageEncoding:
    def test_single_image_3d_tensor(self):
        arr = np.zeros((4, 4, 3), dtype=np.float32)
        out = nodes.SimpleOllamaNode._image_tensor_to_base64_strings(arr)
        assert len(out) == 1
        assert _decode_png(out[0]).size == (4, 4)

    def test_image_batch_4d_tensor(self):
        arr = np.zeros((3, 4, 4, 3), dtype=np.float32)
        out = nodes.SimpleOllamaNode._image_tensor_to_base64_strings(arr)
        assert len(out) == 3

    def test_invalid_shape_raises(self):
        with pytest.raises(RuntimeError):
            nodes.SimpleOllamaNode._image_tensor_to_base64_strings(np.zeros((4,), dtype=np.float32))

    def test_float_values_scaled_to_uint8(self):
        arr = np.ones((2, 2, 3), dtype=np.float32)  # white
        out = nodes.SimpleOllamaNode._image_tensor_to_base64_strings(arr)
        px = np.asarray(_decode_png(out[0]))
        assert px.max() == 255 and px.min() == 255

    def test_fingerprint_changes_with_content(self):
        a = np.zeros((2, 2, 3), dtype=np.float32)
        b = np.ones((2, 2, 3), dtype=np.float32)
        fa = nodes.SimpleOllamaNode._image_fingerprint(a)
        fb = nodes.SimpleOllamaNode._image_fingerprint(b)
        assert fa is not None and fa != fb

    def test_fingerprint_none_for_no_image(self):
        assert nodes.SimpleOllamaNode._image_fingerprint(None) is None


# ---------------------------------------------------------------------------
# _parse_model_info — capability + spec extraction from /api/show
# ---------------------------------------------------------------------------
class TestParseModelInfo:
    def test_extracts_specs(self):
        data = {
            "details": {"family": "gemma3", "parameter_size": "11.8B", "quantization_level": "IQ3_M"},
            "model_info": {"gemma3.context_length": 131072},
        }
        info = nodes._parse_model_info(data)
        assert info["family"] == "gemma3"
        assert info["parameter_size"] == "11.8B"
        assert info["quantization"] == "IQ3_M"
        assert info["context_length"] == 131072

    def test_vision_capability(self):
        info = nodes._parse_model_info({"capabilities": ["completion", "vision"]})
        assert info["vision"] is True
        assert info["thinking"] is False

    def test_thinking_capability(self):
        info = nodes._parse_model_info({"capabilities": ["completion", "thinking"]})
        assert info["thinking"] is True
        assert info["vision"] is False

    def test_both_capabilities(self):
        info = nodes._parse_model_info({"capabilities": ["vision", "thinking", "tools"]})
        assert info["vision"] is True and info["thinking"] is True

    def test_no_capabilities_defaults_false(self):
        info = nodes._parse_model_info({"details": {}, "model_info": {}})
        assert info["vision"] is False and info["thinking"] is False
        assert info["capabilities"] == []

    def test_vision_fallback_via_projector_info(self):
        # Older Ollama servers without a capabilities list still expose projector_info
        info = nodes._parse_model_info({"projector_info": {"clip.vision.something": 1}})
        assert info["vision"] is True

    def test_capabilities_are_lowercased_and_sorted(self):
        info = nodes._parse_model_info({"capabilities": ["Vision", "TOOLS", "completion"]})
        assert info["capabilities"] == ["completion", "tools", "vision"]

    def test_context_length_fallback_from_parameters(self):
        info = nodes._parse_model_info({"parameters": "num_ctx                 8192\nstop \"foo\""})
        assert info["context_length"] == 8192

    def test_missing_fields_use_placeholders(self):
        info = nodes._parse_model_info({})
        assert info["family"] == "?" and info["parameter_size"] == "?"
        assert info["context_length"] is None


# ---------------------------------------------------------------------------
# VALIDATE_INPUTS for the model combo
# ---------------------------------------------------------------------------
class TestValidateInputs:
    def test_rejects_none_model(self):
        result = nodes.SimpleOllamaNode.VALIDATE_INPUTS(model="none", ollama_url="http://localhost:11434")
        assert result is not True

    def test_accepts_real_model(self):
        result = nodes.SimpleOllamaNode.VALIDATE_INPUTS(model="qwen3:8b", ollama_url="http://localhost:11434")
        assert result is True

    def test_reports_bad_url(self):
        result = nodes.SimpleOllamaNode.VALIDATE_INPUTS(model="qwen3:8b", ollama_url="not-a-url")
        assert result is not True
