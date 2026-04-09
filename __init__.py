"""
ComfyUI_Simple_Ollama
=====================
A lightweight, actively-maintained custom node for talking to
any Ollama server (localhost or LAN) from within ComfyUI.

Author : holger@andersundbesser.de
License: MIT
"""

from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

# ComfyUI auto-loads .js files from WEB_DIRECTORY itself, so point directly
# at the folder that contains the extension script.
WEB_DIRECTORY = "./web/js"

__all__ = [
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
    "WEB_DIRECTORY",
]
