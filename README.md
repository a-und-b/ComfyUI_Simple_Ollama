# ComfyUI Simple Ollama 🦙

A lightweight, no-nonsense custom node for talking to any [Ollama](https://ollama.com) server — local or on your LAN — directly from ComfyUI.

Built because most Ollama integrations are buried in huge node packs or abandoned repos. This one does one thing well: send a prompt (with optional image) to Ollama, get text back.

## Features

- **One-click Connect** — enter your Ollama URL, hit Connect, and the node auto-discovers all available models
- **Live model info** — shows parameter count, quantization, model family and context window for the selected model
- **Vision support** — pipe any IMAGE node in and the model sees it (works with Gemma 3, LLaVA, Qwen-VL, etc.)
- **Thinking mode** — get the model's chain-of-thought as a separate output (QwQ, DeepSeek-R1, …)
- **JSON mode** — force valid JSON output for structured pipelines
- **Smart context window** — `num_ctx` auto-adjusts to the selected model's max context length
- **VRAM management** — `keep_alive` controls how long the model stays loaded (set to -1 for always-on, 0 to free VRAM immediately)
- **Prompt passthrough** — third output returns the exact prompt that was sent, useful for debugging or logging

## Installation

1. Navigate to your ComfyUI custom nodes folder:
   ```
   cd /path/to/ComfyUI/custom_nodes/
   ```
2. Clone this repository:
   ```
   git clone https://github.com/a-und-b/ComfyUI_Simple_Ollama.git
   ```
3. Restart ComfyUI

No additional dependencies needed — uses only Python stdlib + PIL/numpy (already part of ComfyUI).

## Usage

1. Add the **Simple Ollama 🦙** node (category: `AI/Ollama`)
2. Enter your Ollama server URL (e.g. `http://192.168.1.100:11434`)
3. Click **🔌 Connect** — the model dropdown populates automatically
4. Select a model — info bar shows parameters, quantization and context window
5. Write your prompt, adjust settings, queue the workflow

### Inputs

| Input | Type | Required | Description |
|---|---|---|---|
| `ollama_url` | STRING | ✅ | Ollama server URL |
| `model` | COMBO | ✅ | Model selector (populated via Connect) |
| `prompt` | STRING | ✅ | Your prompt — context, instructions, question, all in one field |
| `seed` | INT | ✅ | Random seed (0 = random each run) |
| `max_tokens` | INT | ✅ | Max tokens to generate |
| `temperature` | FLOAT | ✅ | Sampling temperature (0 = deterministic) |
| `num_ctx` | INT | ✅ | Context window size in tokens |
| `keep_alive` | FLOAT | ✅ | Minutes to keep model in VRAM (-1 = forever) |
| `thinking_mode` | BOOL | ✅ | Enable chain-of-thought reasoning |
| `json_mode` | BOOL | ✅ | Force valid JSON output |
| `image` | IMAGE | ❌ | Optional image for vision models |
| `system_prompt` | STRING | ❌ | System-level instruction |

### Outputs

| Output | Description |
|---|---|
| `response` | The model's text response |
| `thinking` | The model's reasoning trace (empty if thinking mode is off) |
| `prompt_sent` | The exact prompt that was sent (for debugging/logging) |

## Requirements

- [Ollama](https://ollama.com) running somewhere reachable (localhost or LAN)
- ComfyUI (any recent version)
- That's it. No pip installs, no API keys, no accounts.

## License

MIT — see [LICENSE](LICENSE) for details.
