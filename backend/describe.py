# -*- coding: utf-8 -*-
# use DeepSeek LLM to turn a movie/object name into a 3D generation prompt
import os
import json
import urllib.request

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"

SYSTEM_PROMPT = (
    "You are an expert at writing prompts for AI 3D model generation. "
    "Given a movie/game/object name (possibly in Chinese), output ONE concise English prompt "
    "that describes the physical 3D form: overall shape, structure, key parts, and materials. "
    "Focus on a single printable object/subject. Keep it under 60 words. "
    "Output ONLY the prompt text, no quotes, no explanation."
)

def build_prompt(source_text):
    # returns (prompt, used_llm). falls back to the raw text if no key or on error.
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key or not source_text or not source_text.strip():
        return source_text or "", False
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": source_text.strip()},
        ],
        "temperature": 0.7,
        "max_tokens": 150,
    }
    try:
        req = urllib.request.Request(
            DEEPSEEK_URL,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
        )
        r = json.loads(urllib.request.urlopen(req, timeout=40).read())
        text = r["choices"][0]["message"]["content"].strip()
        return text, True
    except Exception as e:
        print("deepseek prompt build failed:", e)
        return source_text, False
