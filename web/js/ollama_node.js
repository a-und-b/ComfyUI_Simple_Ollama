/**
 * ComfyUI_Simple_Ollama – frontend extension
 *
 * What this does:
 *  1. Adds a "🔌 Connect" button that loads available models from Ollama.
 *  2. Shows model info (params, quant, context window) in a second button.
 *     Connect + info sit between the model combo and the prompt (reordered
 *     safely so seed / control-after-generate stay paired).
 *  3. Persists the last-used URL in localStorage across page reloads.
 */

import { app } from "../../scripts/app.js";

const NODE_NAME    = "SimpleOllamaNode";
const ROUTE_MODELS = "/simple_ollama/models";
const ROUTE_INFO   = "/simple_ollama/model_info";
const LS_KEY_URL   = "simple_ollama_last_url";

app.registerExtension({
    name: "Comfy.SimpleOllama",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_NAME) return;

        const _onNodeCreated = nodeType.prototype.onNodeCreated;

        nodeType.prototype.onNodeCreated = function () {
            _onNodeCreated?.apply(this, arguments);

            const node = this;

            // --- Locate existing widgets --------------------------------
            const urlWidget   = findWidget(node, "ollama_url");
            const modelWidget = findWidget(node, "model");

            if (!urlWidget || !modelWidget) {
                console.warn("[SimpleOllama] Could not find expected widgets.");
                return;
            }

            // Restore last URL
            const savedUrl = localStorage.getItem(LS_KEY_URL);
            if (savedUrl && urlWidget.value === urlWidget.options?.default) {
                urlWidget.value = savedUrl;
            }

            // --- Connect button (moved after model, before prompt) -------
            const btnConnect = node.addWidget(
                "button",
                "🔌 Connect",
                null,
                async () => {
                    const ollamaUrl = urlWidget.value?.trim();
                    if (!ollamaUrl) {
                        setBtn(btnConnect, "⚠️ Enter URL first", node);
                        return;
                    }

                    setBtn(btnConnect, "⏳ Connecting…", node);
                    localStorage.setItem(LS_KEY_URL, ollamaUrl);

                    try {
                        const resp = await fetch(
                            `${ROUTE_MODELS}?url=${encodeURIComponent(ollamaUrl)}`
                        );
                        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
                        const data = await resp.json();

                        if (data.success && data.models.length > 0) {
                            modelWidget.options.values = data.models;
                            if (!data.models.includes(modelWidget.value)) {
                                modelWidget.value = data.models[0];
                            }
                            setBtn(
                                btnConnect,
                                `✅ ${data.models.length} model${data.models.length !== 1 ? "s" : ""}`,
                                node
                            );
                            // Fetch info for the initially selected model
                            fetchModelInfo(urlWidget, modelWidget, btnInfo, node);
                        } else {
                            const msg = data.error ?? "No models found";
                            setBtn(btnConnect, `❌ ${truncate(msg, 40)}`, node);
                        }
                    } catch (err) {
                        setBtn(btnConnect, `❌ ${truncate(err.message, 40)}`, node);
                        console.error("[SimpleOllama] Connect error:", err);
                    }
                },
                { serialize: false }
            );

            // --- Info button (after model) – disabled, acts as label ----
            // Using a button widget as a read-only display row; clicking it
            // re-fetches the info. No "text" type exists in ComfyUI.
            const btnInfo = node.addWidget(
                "button",
                "ℹ️ Connect first to see model info",
                null,
                () => {
                    // Click to manually re-fetch info
                    fetchModelInfo(urlWidget, modelWidget, btnInfo, node);
                },
                { serialize: false }
            );

            // Place: url → model → 🔌 Connect → ℹ️ info → prompt → …
            // Only insert *after* model so prompt + seed + control_after_generate
            // stay contiguous (inserting after url broke that pairing before).
            repositionWidget(node, btnConnect, modelWidget);
            repositionWidget(node, btnInfo, btnConnect);

            // --- Refresh info whenever model combo changes --------------
            const _origCallback = modelWidget.callback;
            modelWidget.callback = function (value) {
                _origCallback?.call(this, value);
                fetchModelInfo(urlWidget, modelWidget, btnInfo, node);
            };

            // Saved graphs: model may already be set but info row never updated
            if (modelWidget.value && modelWidget.value !== "none" && urlWidget.value?.trim()) {
                queueMicrotask(() =>
                    fetchModelInfo(urlWidget, modelWidget, btnInfo, node)
                );
            }
        };
    },
});

// ---------------------------------------------------------------------------
// Fetch model info and update the info button label
// ---------------------------------------------------------------------------

async function fetchModelInfo(urlWidget, modelWidget, btnInfo, node) {
    const ollamaUrl = urlWidget.value?.trim();
    const modelName = modelWidget.value;
    if (!ollamaUrl || !modelName || modelName === "none") return;

    setBtn(btnInfo, "⏳ Loading model info…", node);

    try {
        const resp = await fetch(
            `${ROUTE_INFO}?url=${encodeURIComponent(ollamaUrl)}&model=${encodeURIComponent(modelName)}`
        );
        const data = await resp.json();

        if (data.success) {
            const parts = [];
            if (data.parameter_size && data.parameter_size !== "?") parts.push(data.parameter_size);
            if (data.family        && data.family        !== "?")   parts.push(data.family);
            if (data.quantization  && data.quantization  !== "?")   parts.push(data.quantization);
            if (data.context_length) parts.push(`ctx ${(data.context_length).toLocaleString()}`);

            setBtn(
                btnInfo,
                parts.length > 0 ? `ℹ️  ${parts.join("  ·  ")}` : "ℹ️  No details available",
                node
            );
        } else {
            setBtn(btnInfo, `⚠️  ${truncate(data.error || "Unknown error", 50)}`, node);
        }
    } catch (err) {
        setBtn(btnInfo, `⚠️  ${truncate(err.message, 50)}`, node);
    }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function findWidget(node, name) {
    return node.widgets?.find(w => w.name === name) ?? null;
}

function setBtn(widget, label, node) {
    widget.name = label;
    node.setDirtyCanvas(true, true);
}

function truncate(str, maxLen) {
    return str.length > maxLen ? str.slice(0, maxLen - 1) + "…" : str;
}

function repositionWidget(node, target, anchor) {
    const widgets = node.widgets;
    if (!widgets) return;
    const anchorIdx = widgets.indexOf(anchor);
    const targetIdx = widgets.indexOf(target);
    if (anchorIdx === -1 || targetIdx === -1) return;
    if (targetIdx === anchorIdx + 1) return;
    widgets.splice(targetIdx, 1);
    const newIdx = widgets.indexOf(anchor) + 1;
    widgets.splice(newIdx, 0, target);
}
