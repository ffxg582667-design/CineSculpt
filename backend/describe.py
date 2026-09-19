# -*- coding: utf-8 -*-
# use an OpenAI-compatible LLM to turn a movie/object name into a 3D generation prompt
# works with DeepSeek / OpenAI / Qwen / Moonshot etc (any OpenAI-compatible chat API)
import os
import json
import urllib.request

DEFAULT_BASE = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"

SYSTEM_PROMPT = (
    "You are an expert at writing prompts for AI 3D model generation. "
    "Given a movie/game/object name (possibly in Chinese), output ONE concise English prompt "
    "that describes the physical 3D form: overall shape, structure, key parts, and materials. "
    "Focus on a single printable object/subject. Keep it under 60 words. "
    "Output ONLY the prompt text, no quotes, no explanation."
)

def build_prompt(source_text, api_key=None, base_url=None, model=None):
    # returns (prompt, used_llm). falls back to raw text if no key or on error.
    key = api_key or os.environ.get("LLM_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")
    if not key or not source_text or not source_text.strip():
        return source_text or "", False
    base = (base_url or os.environ.get("LLM_BASE_URL") or DEFAULT_BASE).rstrip("/")
    mdl = model or os.environ.get("LLM_MODEL") or DEFAULT_MODEL
    url = base + "/chat/completions"
    payload = {
        "model": mdl,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": source_text.strip()},
        ],
        "temperature": 0.7,
        "max_tokens": 150,
    }
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
        )
        r = json.loads(urllib.request.urlopen(req, timeout=40).read())
        text = r["choices"][0]["message"]["content"].strip()
        return text, True
    except Exception as e:
        print("llm prompt build failed:", e)
        return source_text, False
