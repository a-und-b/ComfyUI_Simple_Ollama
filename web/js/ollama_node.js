/**
 * ComfyUI_Simple_Ollama – frontend extension
 *
 * What this does:
 *  1. Adds a "Connect" button that loads available models from Ollama.
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

// Human-friendly display labels for widgets and input/output slots. Purely
// cosmetic — the underlying widget/slot `name` (used for serialization) stays
// untouched, so existing workflows keep working.
const NICE_LABELS = {
    ollama_url: "Ollama URL",
    ollama_url_override: "Ollama URL (shared)",
    model: "Model",
    prompt: "Prompt",
    seed: "Seed",
    control_after_generate: "Control After Generate",
    max_tokens: "Max Tokens",
    temperature: "Temperature",
    keep_alive: "Keep Alive (min)",
    thinking_mode: "Thinking Mode",
    system_prompt: "System Prompt",
    image: "Image",
    response: "Response",
    thinking: "Thinking",
    prompt_text: "Prompt Text",
};

function applyNiceLabels(node) {
    for (const collection of [node.widgets, node.inputs, node.outputs]) {
        for (const item of collection ?? []) {
            const nice = NICE_LABELS[item?.name];
            if (nice) item.label = nice;
        }
    }
    node.setDirtyCanvas?.(true, true);
}

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
            "Connect",
            null,
            async () => {
                const { url: ollamaUrl, sourceWidget } = getEffectiveOllamaUrl(node, urlWidget);
                if (!ollamaUrl) {
                    setBtn(btnConnect, "Enter URL first", node);
                    return;
                }

                setBtn(btnConnect, "Connecting…", node);
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
                        setBtn(btnConnect, truncate(msg, 40), node);
                    }
                } catch (err) {
                    setBtn(btnConnect, truncate(err.message, 40), node);
                    console.error("[SimpleOllama] Connect error:", err);
                }
            },
            { serialize: false }
        );

        // Model info is shown in a read-only DOM widget instead of a button
        // label: button labels do not re-render reliably in the Nodes 2.0 (Vue)
        // renderer, whereas a DOM element we mutate directly works in both.
        const infoWidget = createInfoWidget(node);

        node.simpleOllamaState = {
            urlWidget,
            modelWidget,
            btnConnect,
            infoWidget,
            infoEl: infoWidget.infoEl,
        };

        repositionWidget(node, btnConnect, modelWidget);
        repositionWidget(node, infoWidget, btnConnect);
        applyNiceLabels(node);

        const originalCallback = modelWidget.callback;
        modelWidget.callback = function (value) {
            originalCallback?.call(this, value);
            fetchModelInfo(node);
        };

        if (modelWidget.value && modelWidget.value !== "none" && getEffectiveOllamaUrl(node, urlWidget).url) {
            queueMicrotask(() => fetchModelInfo(node));
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
            "Connect Downstream",
            null,
            async () => {
                const ollamaUrl = urlWidget.value?.trim();
                if (!ollamaUrl) {
                    setBtn(btnConnect, "Enter URL first", node);
                    return;
                }

                setBtn(btnConnect, "Connecting…", node);
                localStorage.setItem(LS_KEY_URL, ollamaUrl);

                try {
                    const data = await fetchJson(
                        `${ROUTE_MODELS}?url=${encodeURIComponent(ollamaUrl)}`
                    );

                    if (!(data.success && data.models.length > 0)) {
                        const msg = data.error ?? "No models found";
                        setBtn(btnConnect, truncate(msg, 40), node);
                        return;
                    }

                    const updatedCount = updateConnectedSimpleNodes(node, data.models, ollamaUrl);
                    setBtn(
                        btnConnect,
                        `${updatedCount} node${updatedCount !== 1 ? "s" : ""} · ${data.models.length} model${data.models.length !== 1 ? "s" : ""}`,
                        node
                    );
                } catch (err) {
                    setBtn(btnConnect, truncate(err.message, 40), node);
                    console.error("[SimpleOllama] Connection node connect error:", err);
                }
            },
            { serialize: false }
        );

        repositionWidget(node, btnConnect, urlWidget);
        applyNiceLabels(node);
    };
}

// ---------------------------------------------------------------------------
// Fetch model info and update the info button label
// ---------------------------------------------------------------------------

async function fetchModelInfo(node) {
    const state = node.simpleOllamaState;
    if (!state) return;

    const { urlWidget, modelWidget, infoEl } = state;
    const { url: ollamaUrl } = getEffectiveOllamaUrl(node, urlWidget);
    const modelName = modelWidget.value;
    if (!ollamaUrl || !modelName || modelName === "none") return;

    setInfo(infoEl, "Loading model info…");

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

            renderModelInfo(infoEl, {
                specs: parts.length > 0 ? parts.join("  ·  ") : "No details available",
                vision: !!data.vision,
                thinking: !!data.thinking,
            });
        } else {
            setInfo(infoEl, truncate(data.error || "Unknown error", 60));
        }
    } catch (err) {
        setInfo(infoEl, truncate(err.message, 60));
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
    // Set both name and label: legacy LiteGraph reads `name`, Nodes 2.0 (Vue)
    // prefers `label` when present.
    widget.name = label;
    widget.label = label;
    node.setDirtyCanvas(true, true);
}

// Read-only DOM widget that displays the selected model's info. Works in both
// the legacy canvas renderer and the Nodes 2.0 (Vue) renderer, unlike a button
// label which Vue does not re-render on mutation.
function createInfoWidget(node) {
    const el = document.createElement("div");
    el.textContent = "Connect to see model info";
    Object.assign(el.style, {
        // ComfyUI's DOM-widget wrapper measures the element's own height, so set
        // an explicit height here instead of overriding widget.computeSize —
        // a computeSize override collapses the wrapper to ~8px in the legacy
        // canvas renderer and clips the content.
        height: "22px",
        minHeight: "22px",
        boxSizing: "border-box",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "0 8px",
        fontSize: "11px",
        lineHeight: "16px",
        opacity: "0.85",
        whiteSpace: "nowrap",
        overflow: "hidden",
        textOverflow: "ellipsis",
        fontFamily: "var(--font-family, system-ui, sans-serif)",
    });

    const widget = node.addDOMWidget("model_info", "info", el, {
        serialize: false,
        hideOnZoom: false,
        getValue: () => "",
        setValue: () => {},
    });
    widget.infoEl = el;
    return widget;
}

function setInfo(el, text) {
    if (el) {
        el.textContent = text;
        el.title = text;
    }
}

// Render model specs plus clear, colour-coded capability chips for vision and
// thinking support. Built from DOM nodes so it renders identically in the
// legacy and Nodes 2.0 renderers.
const CHIP_COLORS = {
    vision: "#10b981",   // emerald
    thinking: "#8b5cf6", // violet
};

function makeChip(label, on, color) {
    const chip = document.createElement("span");
    chip.textContent = label;
    Object.assign(chip.style, {
        display: "inline-block",
        verticalAlign: "middle",
        marginLeft: "6px",
        padding: "0 7px",
        borderRadius: "9px",
        fontSize: "10px",
        lineHeight: "16px",
        fontWeight: "700",
        letterSpacing: "0.02em",
        whiteSpace: "nowrap",
        color: on ? "#fff" : "var(--descrip-text, #9aa0a6)",
        background: on ? color : "transparent",
        border: `1px solid ${on ? color : "var(--border-color, #555)"}`,
        opacity: on ? "1" : "0.45",
    });
    chip.title = `${label}: ${on ? "supported" : "not supported"}`;
    return chip;
}

function renderModelInfo(el, { specs, vision, thinking }) {
    if (!el) return;
    el.textContent = "";
    el.style.whiteSpace = "nowrap";

    const specSpan = document.createElement("span");
    specSpan.textContent = specs;
    specSpan.style.opacity = "0.7";
    specSpan.style.verticalAlign = "middle";
    el.appendChild(specSpan);

    el.appendChild(makeChip("Vision", vision, CHIP_COLORS.vision));
    el.appendChild(makeChip("Thinking", thinking, CHIP_COLORS.thinking));

    el.title =
        `${specs} — Vision: ${vision ? "yes" : "no"}, ` +
        `Thinking: ${thinking ? "yes" : "no"}`;
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
            `${models.length} model${models.length !== 1 ? "s" : ""}`,
            node
        );
    }

    if (state.infoEl) {
        fetchModelInfo(node);
    }

    node.setDirtyCanvas(true, true);
    return true;
}

function updateConnectedSimpleNodes(connectionNode, models, ollamaUrl) {
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

        // Overwrite the downstream node's own ollama_url widget so it reflects
        // the shared URL instead of leaving the default placeholder visible.
        if (ollamaUrl) {
            const targetUrlWidget = findWidget(targetNode, "ollama_url");
            if (targetUrlWidget) targetUrlWidget.value = ollamaUrl;
        }

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
