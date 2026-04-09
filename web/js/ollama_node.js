/**
 * ComfyUI_Simple_Ollama – frontend extension
 *
 * What this does:
 *  1. Adds a "🔌 Connect" button that loads available models from Ollama.
 *  2. Shows model info (params, quant, context window) when a model is selected.
 *  3. Persists the last-used URL in localStorage across page reloads.
 */

import { app } from "../../scripts/app.js";

const NODE_NAME       = "SimpleOllamaNode";
const ROUTE_MODELS    = "/simple_ollama/models";
const ROUTE_INFO      = "/simple_ollama/model_info";
const LS_KEY_URL      = "simple_ollama_last_url";

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
            const numCtxWidget = findWidget(node, "num_ctx");

            if (!urlWidget || !modelWidget) {
                console.warn("[SimpleOllama] Could not find expected widgets.");
                return;
            }

            // Restore last URL
            const savedUrl = localStorage.getItem(LS_KEY_URL);
            if (savedUrl && urlWidget.value === urlWidget.options?.default) {
                urlWidget.value = savedUrl;
            }

            // --- Model info label (non-interactive, read-only) ----------
            const infoWidget = node.addWidget(
                "text",         // read-only text display
                "model_info",
                "ℹ️ Select a model to see details",
                () => {},
                { serialize: false }
            );
            // Make it non-editable
            infoWidget.disabled = true;

            // --- Connect button -----------------------------------------
            const btnWidget = node.addWidget(
                "button",
                "🔌 Connect",
                null,
                async () => {
                    const ollamaUrl = urlWidget.value?.trim();
                    if (!ollamaUrl) {
                        setBtn(btnWidget, "⚠️ Enter URL first", node);
                        return;
                    }

                    setBtn(btnWidget, "⏳ Connecting…", node);
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
                                btnWidget,
                                `✅ ${data.models.length} model${data.models.length !== 1 ? "s" : ""}`,
                                node
                            );

                            // Fetch info for the initially selected model
                            fetchModelInfo(urlWidget, modelWidget, numCtxWidget, infoWidget, node);
                        } else {
                            const msg = data.error ?? "No models found";
                            setBtn(btnWidget, `❌ ${truncate(msg, 40)}`, node);
                        }
                    } catch (err) {
                        setBtn(btnWidget, `❌ ${truncate(err.message, 40)}`, node);
                        console.error("[SimpleOllama] Fetch error:", err);
                    }
                },
                { serialize: false }
            );

            // --- Reorder: URL → Connect → Model → Info → rest ----------
            repositionWidget(node, btnWidget, urlWidget);
            repositionWidget(node, infoWidget, modelWidget);

            // --- Fetch model info whenever the model combo changes ------
            const _origCallback = modelWidget.callback;
            modelWidget.callback = function (value) {
                _origCallback?.call(this, value);
                fetchModelInfo(urlWidget, modelWidget, numCtxWidget, infoWidget, node);
            };
        };
    },
});

// ---------------------------------------------------------------------------
// Fetch and display model info
// ---------------------------------------------------------------------------

async function fetchModelInfo(urlWidget, modelWidget, numCtxWidget, infoWidget, node) {
    const ollamaUrl = urlWidget.value?.trim();
    const modelName = modelWidget.value;
    if (!ollamaUrl || !modelName || modelName === "none") return;

    infoWidget.value = "⏳ Loading info…";
    node.setDirtyCanvas(true, true);

    try {
        const resp = await fetch(
            `${ROUTE_INFO}?url=${encodeURIComponent(ollamaUrl)}&model=${encodeURIComponent(modelName)}`
        );
        const data = await resp.json();

        if (data.success) {
            const parts = [];
            if (data.parameter_size && data.parameter_size !== "?") parts.push(data.parameter_size);
            if (data.family && data.family !== "?")                 parts.push(data.family);
            if (data.quantization && data.quantization !== "?")     parts.push(data.quantization);
            if (data.context_length)                                parts.push(`ctx: ${data.context_length.toLocaleString()}`);

            infoWidget.value = parts.length > 0
                ? `ℹ️ ${parts.join(" · ")}`
                : "ℹ️ No details available";

            // Auto-suggest: update num_ctx to match model's context window
            if (data.context_length && numCtxWidget) {
                const currentCtx = numCtxWidget.value;
                const modelCtx   = data.context_length;
                // Only auto-adjust if user still has the default 4096
                if (currentCtx === 4096 && modelCtx !== 4096) {
                    numCtxWidget.value = modelCtx;
                }
            }
        } else {
            infoWidget.value = `⚠️ ${truncate(data.error || "Unknown error", 50)}`;
        }
    } catch (err) {
        infoWidget.value = `⚠️ ${truncate(err.message, 50)}`;
    }

    node.setDirtyCanvas(true, true);
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
