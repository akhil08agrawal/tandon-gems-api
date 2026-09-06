#!/usr/bin/env python3
"""Twice-daily publisher. Promotes drafts whose scheduledFor has passed and whose reviewStatus is auto (at most N per run),
keeps the calendar's publishedAt, pings IndexNow, and warns the Ops group when the runway is short.
Env: SANITY_API_TOKEN (required), SANITY_PROJECT_ID, SANITY_DATASET, WA_OPS_WEBHOOK (optional), INDEXNOW_KEY (optional), PUBLISH_PAUSED=1 to pause.
Usage: auto_publish.py [--limit 2] [--dry]"""
import json, os, sys, datetime, urllib.request, urllib.error, urllib.parse
PROJECT = os.environ.get("SANITY_PROJECT_ID", "68f1un3b"); DATASET = os.environ.get("SANITY_DATASET", "production"); API = "v2025-09-01"
BASE = f"https://{PROJECT}.api.sanity.io/{API}"; SITE = os.environ.get("SITE_URL", "https://tandon-gems.vercel.app")
TOKEN = os.environ.get("SANITY_API_TOKEN") or sys.exit("SANITY_API_TOKEN missing")
def req(method, url, data=None, headers=None):
    h = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}; h.update(headers or {})
    r = urllib.request.Request(url, data=json.dumps(data).encode() if data is not None else None, method=method, headers=h)
    with urllib.request.urlopen(r, timeout=120) as resp: return json.load(resp)
def query(groq, params=None):
    q = {"query": groq, "perspective": "raw"}; [q.__setitem__(f"${k}", json.dumps(v)) for k, v in (params or {}).items()]
    return req("GET", f"{BASE}/data/query/{DATASET}?{urllib.parse.urlencode(q)}")["result"]
def wa(text, key):
    hook = os.environ.get("WA_OPS_WEBHOOK")
    if not hook: return
    try: urllib.request.urlopen(urllib.request.Request(hook, data=json.dumps({"text": text}).encode(), method="POST", headers={"Content-Type": "application/json", "Idempotency-Key": key}), timeout=60)
    except Exception as e: print("wa failed", str(e)[:100])
def indexnow(urls):
    key = os.environ.get("INDEXNOW_KEY")
    if not key or not urls: return
    try: urllib.request.urlopen(urllib.request.Request("https://api.indexnow.org/indexnow", data=json.dumps({"host": urllib.parse.urlparse(SITE).netloc, "key": key, "keyLocation": f"{SITE}/{key}.txt", "urlList": urls}).encode(), method="POST", headers={"Content-Type": "application/json; charset=utf-8"}), timeout=60); print("indexnow pinged", len(urls))
    except Exception as e: print("indexnow failed", str(e)[:100])
def main():
    a = sys.argv[1:]; limit = int(a[a.index("--limit") + 1]) if "--limit" in a else 2; dry = "--dry" in a
    if os.environ.get("PUBLISH_PAUSED") == "1": print("paused by PUBLISH_PAUSED"); return
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    due = query('*[_type == "post" && _id in path("drafts.**") && defined(scheduledFor) && scheduledFor <= $now && coalesce(reviewStatus, "auto") == "auto"] | order(scheduledFor asc) [0...$n]', {"now": now, "n": limit})
    print(f"{len(due)} due (limit {limit}) at {now}")
    published = []
    for d in due:
        slug = d["slug"]["current"]; live = {k: v for k, v in d.items() if k not in ("_rev", "_createdAt", "_updatedAt")}; live["_id"] = f"post-{slug}"
        live.pop("scheduledFor", None); live["publishedAt"] = live.get("publishedAt") or now
        if dry: print("would publish", slug, "dated", live["publishedAt"]); continue
        req("POST", f"{BASE}/data/mutate/{DATASET}", {"mutations": [{"createOrReplace": live}, {"delete": {"id": d["_id"]}}]}); published.append(slug); print("published", slug, "dated", live["publishedAt"])
    if published: indexnow([f"{SITE}/blog/{s}" for s in published] + [f"{SITE}/blog", f"{SITE}/sitemap.xml"])
    left = query('count(*[_type == "post" && _id in path("drafts.**") && defined(scheduledFor) && coalesce(reviewStatus, "auto") == "auto"])')
    print("scheduled drafts left:", left)
    morning = datetime.datetime.now(datetime.timezone.utc).hour < 12  # one alert a day, on the first run
    if left < 14 and (published or left > 0) and morning and not dry: wa(f"Blog runway: {left} scheduled drafts left (two publish per day). Time to generate the next batch.", f"runway-{datetime.date.today().isoformat()}")
if __name__ == "__main__": main()
