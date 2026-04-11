/**
 * ComfyUI_Simple_Ollama – frontend extension
 *
 * What this does:
 *  1. Adds a "🔌 Connect" button that loads available models from Ollama.
 *  2. Shows model info (params, quant, context window) in a second button.
 *     Connect + info sit between the model combo and the prompt (reordered
 *     safely so seed / control-after-generate stay paired).
 *  3. Persists the last-used URL in localStorage across page reloads.
 *  4. Lets the Ollama Connection node push model updates to all connected
 *     Simple Ollama nodes in one click.
 */

import { app } from "../../scripts/app.js";

const NODE_NAME = "SimpleOllamaNode";
const CONNECTION_NODE_NAME = "SimpleOllamaConnectionNode";
const ROUTE_MODELS = "/simple_ollama/models";
const ROUTE_INFO = "/simple_ollama/model_info";
const LS_KEY_URL = "simple_ollama_last_url";
const OVERRIDE_INPUT_NAME = "ollama_url_override";

app.registerExtension({
    name: "Comfy.SimpleOllama",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name === NODE_NAME) {
            registerSimpleOllamaNode(nodeType);
        } else if (nodeData.name === CONNECTION_NODE_NAME) {
            registerConnectionNode(nodeType);
        }
    },
});

function registerSimpleOllamaNode(nodeType) {
    const originalOnNodeCreated = nodeType.prototype.onNodeCreated;

    nodeType.prototype.onNodeCreated = function () {
        originalOnNodeCreated?.apply(this, arguments);

        const node = this;
        const urlWidget = findWidget(node, "ollama_url");
        const modelWidget = findWidget(node, "model");

        if (!urlWidget || !modelWidget) {
            console.warn("[SimpleOllama] Could not find expected widgets.");
            return;
        }

        restoreSavedUrl(urlWidget);

        const btnConnect = node.addWidget(
            "button",
            "🔌 Connect",
            null,
            async () => {
                const { url: ollamaUrl, sourceWidget } = getEffectiveOllamaUrl(node, urlWidget);
                if (!ollamaUrl) {
                    setBtn(btnConnect, "⚠️ Enter URL first", node);
                    return;
                }

                setBtn(btnConnect, "⏳ Connecting…", node);
                if (sourceWidget === urlWidget) {
                    localStorage.setItem(LS_KEY_URL, ollamaUrl);
                }

                try {
                    const data = await fetchJson(
                        `${ROUTE_MODELS}?url=${encodeURIComponent(ollamaUrl)}`
                    );

                    if (data.success && data.models.length > 0) {
                        applyModelsToSimpleNode(node, data.models);
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

        const btnInfo = node.addWidget(
            "button",
            "ℹ️ Connect first to see model info",
            null,
            () => {
                fetchModelInfo(node, urlWidget, modelWidget, btnInfo);
            },
            { serialize: false }
        );

        node.simpleOllamaState = {
            urlWidget,
            modelWidget,
            btnConnect,
            btnInfo,
        };

        repositionWidget(node, btnConnect, modelWidget);
        repositionWidget(node, btnInfo, btnConnect);

        const originalCallback = modelWidget.callback;
        modelWidget.callback = function (value) {
            originalCallback?.call(this, value);
            fetchModelInfo(node, urlWidget, modelWidget, btnInfo);
        };

        if (modelWidget.value && modelWidget.value !== "none" && getEffectiveOllamaUrl(node, urlWidget).url) {
            queueMicrotask(() => fetchModelInfo(node, urlWidget, modelWidget, btnInfo));
        }
    };
}

function registerConnectionNode(nodeType) {
    const originalOnNodeCreated = nodeType.prototype.onNodeCreated;

    nodeType.prototype.onNodeCreated = function () {
        originalOnNodeCreated?.apply(this, arguments);

        const node = this;
        const urlWidget = findWidget(node, "ollama_url");
        if (!urlWidget) {
            console.warn("[SimpleOllama] Connection node missing ollama_url widget.");
            return;
        }

        restoreSavedUrl(urlWidget);

        const btnConnect = node.addWidget(
            "button",
            "🔌 Connect Downstream",
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
                    const data = await fetchJson(
                        `${ROUTE_MODELS}?url=${encodeURIComponent(ollamaUrl)}`
                    );

                    if (!(data.success && data.models.length > 0)) {
                        const msg = data.error ?? "No models found";
                        setBtn(btnConnect, `❌ ${truncate(msg, 40)}`, node);
                        return;
                    }

                    const updatedCount = updateConnectedSimpleNodes(node, data.models);
                    setBtn(
                        btnConnect,
                        `✅ ${updatedCount} node${updatedCount !== 1 ? "s" : ""} · ${data.models.length} model${data.models.length !== 1 ? "s" : ""}`,
                        node
                    );
                } catch (err) {
                    setBtn(btnConnect, `❌ ${truncate(err.message, 40)}`, node);
                    console.error("[SimpleOllama] Connection node connect error:", err);
                }
            },
            { serialize: false }
        );

        repositionWidget(node, btnConnect, urlWidget);
    };
}

// ---------------------------------------------------------------------------
// Fetch model info and update the info button label
// ---------------------------------------------------------------------------

async function fetchModelInfo(node, urlWidget, modelWidget, btnInfo) {
    const { url: ollamaUrl } = getEffectiveOllamaUrl(node, urlWidget);
    const modelName = modelWidget.value;
    if (!ollamaUrl || !modelName || modelName === "none") return;

    setBtn(btnInfo, "⏳ Loading model info…", node);

    try {
        const data = await fetchJson(
            `${ROUTE_INFO}?url=${encodeURIComponent(ollamaUrl)}&model=${encodeURIComponent(modelName)}`
        );

        if (data.success) {
            const parts = [];
            if (data.parameter_size && data.parameter_size !== "?") parts.push(data.parameter_size);
            if (data.family && data.family !== "?") parts.push(data.family);
            if (data.quantization && data.quantization !== "?") parts.push(data.quantization);
            if (data.context_length) parts.push(`ctx ${data.context_length.toLocaleString()}`);

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

function restoreSavedUrl(urlWidget) {
    const savedUrl = localStorage.getItem(LS_KEY_URL);
    if (savedUrl && urlWidget.value === urlWidget.options?.default) {
        urlWidget.value = savedUrl;
    }
}

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

function applyModelsToSimpleNode(node, models) {
    const state = node.simpleOllamaState ?? {};
    const modelWidget = state.modelWidget ?? findWidget(node, "model");
    if (!modelWidget || !Array.isArray(models) || models.length === 0) {
        return false;
    }

    modelWidget.options.values = models;
    if (!models.includes(modelWidget.value)) {
        modelWidget.value = models[0];
    }

    if (state.btnConnect) {
        setBtn(
            state.btnConnect,
            `✅ ${models.length} model${models.length !== 1 ? "s" : ""}`,
            node
        );
    }

    if (state.urlWidget && state.btnInfo) {
        fetchModelInfo(node, state.urlWidget, modelWidget, state.btnInfo);
    }

    node.setDirtyCanvas(true, true);
    return true;
}

function updateConnectedSimpleNodes(connectionNode, models) {
    const output = connectionNode.outputs?.find(o => o.name === "ollama_url");
    const linkIds = output?.links ?? [];
    if (!linkIds.length) return 0;

    const graph = connectionNode.graph ?? app.graph;
    let updatedCount = 0;

    for (const linkId of linkIds) {
        const link = graph?.links?.[linkId];
        if (!link) continue;

        const targetNode = graph.getNodeById?.(link.target_id);
        if (!isSimpleOllamaNode(targetNode)) continue;

        const targetInput = targetNode.inputs?.[link.target_slot];
        if (targetInput?.name !== OVERRIDE_INPUT_NAME) continue;

        if (applyModelsToSimpleNode(targetNode, models)) {
            updatedCount += 1;
        }
    }

    return updatedCount;
}

function isSimpleOllamaNode(node) {
    if (!node) return false;
    const nodeName = node.comfyClass ?? node.type ?? node.constructor?.nodeData?.name;
    return nodeName === NODE_NAME;
}

function getEffectiveOllamaUrl(node, fallbackWidget) {
    const linkedValue = getLinkedWidgetValue(node, OVERRIDE_INPUT_NAME, "ollama_url");
    if (linkedValue) {
        return { url: linkedValue.trim(), sourceWidget: null };
    }
    return { url: fallbackWidget.value?.trim() ?? "", sourceWidget: fallbackWidget };
}

function getLinkedWidgetValue(node, inputName, widgetName) {
    const input = node.inputs?.find(i => i.name === inputName);
    if (!input || input.link == null) return null;

    const graph = node.graph ?? app.graph;
    const link = graph?.links?.[input.link];
    if (!link) return null;

    const sourceNode = graph.getNodeById?.(link.origin_id);
    const sourceWidget = sourceNode?.widgets?.find(w => w.name === widgetName);
    if (!sourceWidget || sourceWidget.value == null) return null;

    return String(sourceWidget.value);
}

async function fetchJson(url) {
    const resp = await fetch(url);
    let data = null;

    try {
        data = await resp.json();
    } catch {
        // Leave data null so we can fall back to the HTTP status below.
    }

    if (!resp.ok) {
        throw new Error(data?.error || `HTTP ${resp.status}`);
    }

    return data ?? {};
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
