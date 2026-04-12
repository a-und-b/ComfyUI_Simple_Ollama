# ComfyUI Simple Ollama 🦙

A lightweight, no-nonsense custom node for talking to any [Ollama](https://ollama.com) server directly from ComfyUI.

Built because most Ollama integrations are buried in huge node packs or abandoned repos. This one does one thing well: send a prompt (with optional image input) to Ollama, get text back.

## Features

- **One-click Connect** — enter your Ollama URL, hit Connect, and the node auto-discovers all available models
- **Live model info** — shows parameter count, quantization, model family and context window for the selected model
- **Vision support** — pipe in one IMAGE or an IMAGE batch and every frame is sent to the model (works with Gemma 3, LLaVA, Qwen-VL, etc.)
- **Thinking mode** — get the model's chain-of-thought as a separate output (QwQ, DeepSeek-R1, …)
- **VRAM management** — `keep_alive` controls how long the model stays loaded (`-1` keeps it loaded, `0` unloads immediately)
- **Prompt text output** — third output returns the user prompt text field for debugging or logging

<img width="2812" height="2152" alt="CleanShot 2026-04-10 at 08 10 14@2x" src="https://github.com/user-attachments/assets/264433ff-1b73-482e-8365-b4b1956c8018" />

## Installation

### ComfyUI Manager (recommended)

In [ComfyUI Manager](https://github.com/ltdrdata/ComfyUI-Manager), open the custom-node browser and install **comfyui-simple-ollama** from the [Comfy Registry](https://registry.comfy.org/), then restart ComfyUI.

### Manual (git)

1. Navigate to your ComfyUI custom nodes folder:
   ```
   cd /path/to/ComfyUI/custom_nodes/
   ```
2. Clone this repository:
   ```
   git clone https://github.com/a-und-b/ComfyUI_Simple_Ollama.git
   ```
3. Restart ComfyUI

No extra `pip` step for this pack — it uses the Python stdlib plus PIL/numpy (already bundled with ComfyUI).

## Example workflow

The folder [`example_workflows/`](example_workflows/) contains **`example.json`** (full graph), **`example.png`** (canvas preview), and sample images **`fox.png`** / **`owl.png`**. Copy those two PNGs into your ComfyUI **`input/`** directory (keep the same filenames) so the **Load Image** nodes resolve—then drag **`example.json`** onto the canvas (or load it from the workflow menu) to explore how the **Ollama Connection** node, vision inputs, and downstream nodes are wired. You can swap in your own images by changing the **Load Image** widgets or replacing the files in **`input/`**.

## Usage

1. Add the **Simple Ollama 🦙** node (category: `AI/Ollama`)
2. Enter your Ollama server URL (e.g. `http://192.168.1.100:11434`)
3. Click **🔌 Connect** (between the model field and the prompt) — the model dropdown fills from your server
4. Select a model — the info row shows parameters, quantization, and context window
5. Write your prompt in the field below, adjust other settings, queue the workflow

Notes:
- If you connect an IMAGE batch, every frame is forwarded to Ollama as a separate entry in `messages[].images`.
- The Connect/model-info helper routes proxy to the Ollama URL you enter, so they are intended for trusted/local ComfyUI deployments.

### Multiple Nodes / Shared URL

If you use several **Simple Ollama 🦙** nodes in one workflow, add one **Ollama Connection** node and connect its `ollama_url` output to each node's optional `ollama_url_override` input.

- This lets multiple nodes share one central Ollama server URL.
- The regular `ollama_url` widget still works as a fallback when `ollama_url_override` is not connected.
- The **🔌 Connect** button and model info row will use the shared URL when the override input is wired.
- The **🔌 Connect Downstream** button on `Ollama Connection` fetches models once and updates every connected `Simple Ollama 🦙` node.
- Downstream nodes keep their current model when it still exists; otherwise they switch to the first available model and refresh model info automatically.

### Inputs

| Input | Type | Required | Description |
|---|---|---|---|
| `ollama_url` | STRING | ✅ | Ollama server URL |
| `ollama_url_override` | STRING | ❌ | Optional shared URL input, for example from the `Ollama Connection` node |
| `model` | COMBO | ✅ | Model selector (populated via Connect) |
| `prompt` | STRING | ✅ | Your prompt — context, instructions, question, all in one field |
| `seed` | INT | ✅ | Random seed for reproducible outputs |
| `max_tokens` | INT | ✅ | Max tokens to generate |
| `temperature` | FLOAT | ✅ | Sampling temperature (0 = deterministic) |
| `keep_alive` | FLOAT | ✅ | Minutes to keep the model loaded (`-1` = keep loaded, `0` = unload immediately) |
| `thinking_mode` | BOOL | ✅ | Enable chain-of-thought reasoning |
| `image` | IMAGE | ❌ | Optional vision input; a single image sends one image, an IMAGE batch sends all frames |
| `system_prompt` | STRING | ❌ | System-level instruction |

### Outputs

| Output | Description |
|---|---|
| `response` | The model's text response |
| `thinking` | The model's reasoning trace (empty if thinking mode is off) |
| `prompt_text` | The user prompt text field, returned unchanged for debugging/logging |

### Ollama Connection Outputs

| Output | Description |
|---|---|
| `ollama_url` | The normalized Ollama base URL for downstream Simple Ollama nodes |

## Requirements

- [Ollama](https://ollama.com) running somewhere reachable (localhost or LAN)
- ComfyUI (any recent version) with Python **3.10+** (same as [`pyproject.toml`](pyproject.toml) / typical ComfyUI installs)
- No separate pip install for this node pack, no API keys, no accounts

## License

MIT — see [LICENSE](LICENSE) for details.
