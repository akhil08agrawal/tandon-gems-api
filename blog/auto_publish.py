#!/usr/bin/env python3
"""Twice-daily publisher. Promotes drafts whose scheduledFor has passed and whose reviewStatus is auto (at most N per run),
keeps the calendar's publishedAt, pings IndexNow, and warns the Ops group when the runway is short.
Env: SANITY_API_TOKEN (required), SANITY_PROJECT_ID, SANITY_DATASET, WA_OPS_WEBHOOK (optional), INDEXNOW_KEY (optional), PUBLISH_PAUSED=1 to pause.
Usage: auto_publish.py [--limit 2] [--dry]

Where it runs: the Render cron job tandon-blog-publish (schedule 0 0,16 UTC, which is 17:00 and 09:00 Pacific) from the public mirror
repo akhil08agrawal/tandon-gems-api at blog/auto_publish.py; scripts/sync_api_mirror.sh copies this file there. Standard library only,
keep it that way (the cron installs nothing). Secrets come from Render's environment, never from a file, and SITE_URL may override the site.
Side effects: writes to Sanity (createOrReplace post-<slug>, delete drafts.post-<slug>), which fires the Sanity webhook to
site/app/api/revalidate (page rebuild plus a WhatsApp "New post live" notice); pings IndexNow; may post one runway alert a day to WhatsApp.
Outputs: nothing on disk; log lines only.
Run locally: SANITY_API_TOKEN=... python3 scripts/blog/auto_publish.py --dry
Traps: a draft with reviewStatus auto and a past scheduledFor is published within 12 hours of being pushed, so use --hold in
make_post.py or set reviewStatus hold in Studio for anything that needs a human read. Changing --limit changes how fast the runway
drains (schedule_bank.py assumes two slots a day). The live document keeps the calendar publishedAt, which may be backdated by design.
"""
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
        # Live ids are post-<slug>: no dots, because dotted ids are path-namespaced and invisible to the public API and the site.
        slug = d["slug"]["current"]; live = {k: v for k, v in d.items() if k not in ("_rev", "_createdAt", "_updatedAt")}; live["_id"] = f"post-{slug}"
        live.pop("scheduledFor", None); live["publishedAt"] = live.get("publishedAt") or now
        if dry: print("would publish", slug, "dated", live["publishedAt"]); continue
        req("POST", f"{BASE}/data/mutate/{DATASET}", {"mutations": [{"createOrReplace": live}, {"delete": {"id": d["_id"]}}]}); published.append(slug); print("published", slug, "dated", live["publishedAt"])
    if published: indexnow([f"{SITE}/blog/{s}" for s in published] + [f"{SITE}/blog", f"{SITE}/sitemap.xml"])
    # Catalog edits made in the Studio reach the site only through a build (data/overrides.json is pulled at build time).
    since = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=13)).isoformat(timespec="seconds").replace("+00:00", "Z")
    edited = query('count(*[_type in ["product", "stone", "shape"] && _updatedAt > $since])', {"since": since})
    if edited and os.environ.get("VERCEL_DEPLOY_HOOK") and not dry:
        try: urllib.request.urlopen(urllib.request.Request(os.environ["VERCEL_DEPLOY_HOOK"], method="POST"), timeout=60); print(f"redeploy triggered: {edited} catalog documents edited since {since[:16]}")
        except Exception as e: print("redeploy failed", str(e)[:100])
    left = query('count(*[_type == "post" && _id in path("drafts.**") && defined(scheduledFor) && coalesce(reviewStatus, "auto") == "auto"])')
    print("scheduled drafts left:", left)
    # The cron runs at 00:00 and 16:00 UTC; only the 00:00 run alerts, so the group gets at most one runway message a day.
    morning = datetime.datetime.now(datetime.timezone.utc).hour < 12  # one alert a day, on the first run
    if left < 14 and (published or left > 0) and morning and not dry: wa(f"Blog runway: {left} scheduled drafts left (two publish per day). Time to generate the next batch.", f"runway-{datetime.date.today().isoformat()}")
if __name__ == "__main__": main()
