"""
ComfyUI_Simple_Ollama
=====================
A lightweight, actively-maintained custom node for talking to
any Ollama server (localhost or LAN) from within ComfyUI.

Author : holger@andersundbesser.de
License: MIT
"""

from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

# Tell ComfyUI where to find the JavaScript web extension
WEB_DIRECTORY = "./web"

__all__ = [
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
    "WEB_DIRECTORY",
]
