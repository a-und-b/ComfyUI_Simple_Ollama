"""Headless test bootstrap for ComfyUI_Simple_Ollama.

ComfyUI nodes import ``server`` / ``folder_paths`` at module load. Stub them so
``nodes.py`` imports without a running ComfyUI. ``nodes.py`` only touches
``server``/``aiohttp`` inside a ``try/except ImportError`` (route registration),
so the stub mainly keeps a real ComfyUI install from interfering.
"""

import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

if "server" not in sys.modules:
    server = types.ModuleType("server")

    class _Routes:
        def get(self, *a, **k):
            return lambda fn: fn

        def post(self, *a, **k):
            return lambda fn: fn

    class _Instance:
        routes = _Routes()

    class PromptServer:
        instance = _Instance()

    server.PromptServer = PromptServer
    sys.modules["server"] = server

if "folder_paths" not in sys.modules:
    fp = types.ModuleType("folder_paths")
    fp.base_path = os.path.join(ROOT, "tests", "_no_root")  # non-existent on purpose
    fp.models_dir = os.path.join(ROOT, "tests", "_no_models")
    fp.get_folder_paths = lambda *_a, **_k: []
    sys.modules["folder_paths"] = fp
