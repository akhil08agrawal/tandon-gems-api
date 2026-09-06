#!/usr/bin/env python3
"""Answer-engine adapters for the pulse. Each returns (answer_text, [citation_urls]) for one prompt.
Engines: OpenAI (Responses API with the web_search tool, model gpt-5-mini, citations from url_citation annotations),
Exa (/answer endpoint, citations from the returned list). Anthropic and Gemini adapters activate when their keys exist.
Keys: OPENAI_API_KEY, EXA_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY from the environment or site/.env.local.
Every call costs money (cents). Retries: 3 with backoff on 429 and 5xx. Measures the model layer through the API, not the
consumer chat UI; label results that way."""
import json, os, pathlib, time, urllib.request, urllib.error
ROOT = pathlib.Path(__file__).resolve().parents[2]  # on Render this is the repo root; site/.env.local does not exist there and env vars are used
def env(name):
    v = os.environ.get(name)
    if v: return v
    f = ROOT / "site" / ".env.local"
    if f.exists():
        for line in f.read_text().splitlines():
            if line.startswith(name + "="): return line.split("=", 1)[1].strip()
    return None
def _post(url, body, headers, timeout=180):
    for attempt in range(1, 4):
        try:
            r = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers={"Content-Type": "application/json", **headers})
            with urllib.request.urlopen(r, timeout=timeout) as resp: return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 529) and attempt < 3: time.sleep(5 * attempt); continue
            raise RuntimeError(f"HTTP {e.code}: {e.read()[:300].decode(errors='replace')}")
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < 3: time.sleep(5 * attempt); continue
            raise RuntimeError(str(e)[:200])
def openai(prompt, model="gpt-5-mini"):
    key = env("OPENAI_API_KEY"); assert key, "OPENAI_API_KEY missing"
    d = _post("https://api.openai.com/v1/responses", {"model": model, "tools": [{"type": "web_search"}], "input": prompt}, {"Authorization": f"Bearer {key}"}, timeout=240)
    text, urls = "", []
    for o in d.get("output", []):
        if o.get("type") != "message": continue
        for c in o.get("content", []):
            if c.get("type") == "output_text":
                text += c.get("text", "")
                for a in c.get("annotations", []) or []:
                    if a.get("type") == "url_citation" and a.get("url"): urls.append(a["url"])
    return text, urls
def exa(prompt):
    key = env("EXA_API_KEY"); assert key, "EXA_API_KEY missing"
    d = _post("https://api.exa.ai/answer", {"query": prompt, "text": False}, {"x-api-key": key}, timeout=120)
    return d.get("answer", "") or "", [c.get("url") for c in d.get("citations", []) if c.get("url")]
def anthropic(prompt, model="claude-sonnet-5"):
    key = env("ANTHROPIC_API_KEY"); assert key, "ANTHROPIC_API_KEY missing"
    d = _post("https://api.anthropic.com/v1/messages", {"model": model, "max_tokens": 4000, "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}], "messages": [{"role": "user", "content": prompt}]}, {"x-api-key": key, "anthropic-version": "2023-06-01"}, timeout=600)
    text, urls = "", []
    for b in d.get("content", []):
        if b.get("type") == "text":
            text += b.get("text", "")
            for c in b.get("citations", []) or []:
                if c.get("url"): urls.append(c["url"])
        if b.get("type") == "web_search_tool_result":
            for c in b.get("content", []) or []:
                if isinstance(c, dict) and c.get("url"): urls.append(c["url"])
    return text, urls
def gemini(prompt, model="gemini-2.5-flash"):
    key = env("GEMINI_API_KEY"); assert key, "GEMINI_API_KEY missing"
    d = _post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent", {"contents": [{"parts": [{"text": prompt}]}], "tools": [{"google_search": {}}]}, {"x-goog-api-key": key}, timeout=240)
    cand = (d.get("candidates") or [{}])[0]; text = "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []))
    urls = [c.get("web", {}).get("uri") for c in cand.get("groundingMetadata", {}).get("groundingChunks", []) if c.get("web", {}).get("uri")]
    return text, urls
ENGINES = {"openai": (openai, "OPENAI_API_KEY"), "exa": (exa, "EXA_API_KEY"), "anthropic": (anthropic, "ANTHROPIC_API_KEY"), "gemini": (gemini, "GEMINI_API_KEY")}
def available():
    return [name for name, (_, k) in ENGINES.items() if env(k)]
