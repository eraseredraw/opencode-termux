#!/usr/bin/env python3
"""Regenerate the NeuroAPI provider block in ~/.config/opencode/opencode.json.

Reads the live model inventory from https://neuroapi.host/v1/models (metadata
only, no chat completion, so it costs no tokens) and rewrites the
`providers.neuroapi` map in the OpenCode V2 config. Everything else in the
config is preserved.

Usage:
    NEUROAPI_API_KEY=... python3 ~/bin/neuroapi-sync.py [--dry-run]
"""

import json
import os
import re
import sys
import urllib.request

CONFIG = os.path.expanduser("~/.config/opencode/opencode.json")
API = "https://neuroapi.host/v1/models"

# Non-chat endpoints: they are declared so the config documents them, but they
# never appear in /models because only chat models are selectable.
def media_type(model_id: str) -> str | None:
    m = model_id.lower()
    if re.search(r"(^|-)tts(-|$)|^speech-|whisper", m):
        return "audio"
    if "realtime" in m:
        return "audio"
    if "embedding" in m or "rerank" in m:
        return "embedding"
    if re.search(r"kling|veo-|seedance|happyhorse|grok-video|imagine-video|_videos$", m):
        return "video"
    if "image" in m or m.startswith("seedream") or m == "z-image-turbo":
        return "image"
    return None


# Context/output windows: use the API value when it reports one, otherwise a
# conservative family default (too large a value breaks requests, too small
# only costs an earlier compaction).
CONTEXT_DEFAULTS = [
    (r"^claude-(opus|sonnet|fable)-5", 200_000),
    (r"^claude-", 200_000),
    (r"^gpt-4o", 128_000),
    (r"^gpt-", 400_000),
    (r"^gemini-", 1_048_576),
    (r"^qwen", 262_144),
    (r"^deepseek", 163_840),
    (r"^kimi", 262_144),
    (r"^glm", 200_000),
    (r"^grok", 256_000),
    (r"^minimax", 204_800),
    (r"^hy4", 131_072),
]

OUTPUT_DEFAULTS = [
    (r"^claude-(opus|sonnet|fable)-5", 64_000),
    (r"^claude-", 32_000),
    (r"^gemini-4", 65_536),
    (r"^gemini-", 64_000),
    (r"^gpt-6", 128_000),
    (r"^gpt-", 64_000),
    (r"^qwen", 64_000),
    (r"^deepseek", 64_000),
    (r"^kimi", 64_000),
    (r"^glm", 64_000),
    (r"^grok", 64_000),
    (r"^minimax", 64_000),
]


def pick(patterns, model_id, fallback):
    for pat, value in patterns:
        if re.match(pat, model_id, re.I):
            return value
    return fallback


def capabilities(model_id: str) -> dict:
    m = model_id.lower()
    text_image_video = ["text", "image", "video"]
    if m.startswith("claude"):
        inp = ["text", "image", "pdf"]
    elif m.startswith("gemini"):
        inp = text_image_video + ["audio"]
    elif m.startswith("gpt-4o") or m.startswith("gpt-5") or m.startswith("gpt-6"):
        inp = ["text", "image", "pdf"]
    elif "omni" in m:
        inp = text_image_video + ["audio"]
    elif m.startswith("qwen3.7-plus") or m.startswith("qwen3.7-flash") or m.startswith("qwen3.8"):
        inp = text_image_video
    elif m.startswith("qwen"):
        inp = ["text"]
    elif m.startswith("glm") or m.startswith("kimi") or m.startswith("grok"):
        inp = ["text", "image"]
    else:
        inp = ["text"]
    # qwen3.7-max is described as a text reasoning model, gpt-5-search-api is text only
    if m in ("gpt-5-search-api", "deepseek-v4-pro", "MiniMax-M2.5-highspeed"):
        inp = ["text"]
    return {"tools": True, "input": inp, "output": ["text"]}


def build_models(entries):
    models = {}
    for e in entries:
        mid = e["id"]
        kind = media_type(mid)
        name = (e.get("display_name") or mid).strip()
        entry = {"modelID": mid, "name": name}
        if kind:
            entry["type"] = kind
            entry["disabled"] = True
        else:
            ctx = e.get("context_token_limit") or pick(CONTEXT_DEFAULTS, mid, 262_144)
            out = e.get("output_token_limit") or pick(OUTPUT_DEFAULTS, mid, 32_000)
            entry["capabilities"] = capabilities(mid)
            entry["limit"] = {"context": int(ctx), "output": int(min(out, ctx))}
            # Alibaba-backed Qwen endpoints reject `max_tokens`; they need
            # `max_completion_tokens` or the request fails with a 400.
            if mid.lower().startswith("qwen"):
                entry["compatibility"] = {"maxTokensField": "max_completion_tokens"}
            if e.get("description"):
                entry["name"] = f"{name} — {e['description'].split('.')[0]}"[:120]
        models[mid] = entry
    return models


def main():
    key = os.environ.get("NEUROAPI_API_KEY")
    if not key:
        sys.exit("NEUROAPI_API_KEY is not set")
    req = urllib.request.Request(API, headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=40) as r:
        data = json.load(r)
    entries = sorted(data["data"], key=lambda x: x["id"].lower())
    models = build_models(entries)

    cfg = json.load(open(CONFIG))
    provider = {
        "name": "NeuroAPI",
        "env": ["NEUROAPI_API_KEY"],
        "package": "@opencode/ai/providers/openai-compatible",
        "settings": {
            "baseURL": "https://neuroapi.host/v1",
            "apiKey": "{env:NEUROAPI_API_KEY}",
            "chunkTimeout": False,
        },
        "models": models,
    }
    cfg.setdefault("providers", {})["neuroapi"] = provider
    cfg.pop("provider", None)

    chat = [m for m, v in models.items() if not v.get("disabled")]
    print(f"models: {len(models)} total, {len(chat)} chat")
    if "--dry-run" in sys.argv:
        print(json.dumps(provider["models"], ensure_ascii=False, indent=1)[:1500])
        return
    with open(CONFIG, "w") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("wrote", CONFIG)


if __name__ == "__main__":
    main()
