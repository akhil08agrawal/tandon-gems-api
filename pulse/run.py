#!/usr/bin/env python3
"""AEO pulse: are we cited for the questions we write for?
Asks each available answer engine every prompt in prompts.json, records which domains are cited and whether the brand
is mentioned, scores citation rate, mention rate and share of voice against competitor domains, compares with the previous
snapshot, and writes snapshots/<date>.json plus latest.md. Costs a few cents per prompt per engine.
Usage: run.py [--engines openai,exa] [--repeats 1] [--limit N (probe: writes nothing)] [--wa (post the digest to the Ops group)]
Rules learned from para-gtm-os/aeo/pulse: the prompt set is frozen (append only, with a dated note) or week-to-week
comparison dies; a --limit run never writes a snapshot; a same-day rerun compares against the previous day, not itself;
an engine that fails three times in a row is dropped for the run instead of burning the hour in retries."""
import json, sys, pathlib, datetime, re, collections, urllib.request, urllib.parse
sys.path.insert(0, str(pathlib.Path(__file__).parent)); import engines as E
HERE = pathlib.Path(__file__).parent; SNAP = HERE / "snapshots"; SNAP.mkdir(exist_ok=True)
PROJECT = E.env("SANITY_PROJECT_ID") or "68f1un3b"; DATASET = E.env("SANITY_DATASET") or "production"
def sanity(method, path, body=None):
    """Snapshots also live in Sanity (pulseSnapshot documents) so the Render cron, which has no persistent disk, can compare week to week and the dashboard can chart them."""
    tok = E.env("SANITY_API_TOKEN")
    if not tok: return None
    r = urllib.request.Request(f"https://{PROJECT}.api.sanity.io/v2025-09-01{path}", data=json.dumps(body).encode() if body else None, method=method, headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=60) as resp: return json.load(resp)
    except Exception as e: print("sanity:", str(e)[:120]); return None
def host(u):
    try: h = urllib.parse.urlparse(u).netloc.lower(); return h[4:] if h.startswith("www.") else h
    except Exception: return ""
def main():
    a = sys.argv[1:]; cfg = json.load(open(HERE / "prompts.json"))
    names = (a[a.index("--engines") + 1].split(",") if "--engines" in a else E.available()); names = [n for n in names if n in E.available()]
    repeats = int(a[a.index("--repeats") + 1]) if "--repeats" in a else 1; limit = int(a[a.index("--limit") + 1]) if "--limit" in a else 0
    prompts = cfg["prompts"][:limit] if limit else cfg["prompts"]; ours = [d.lower() for d in cfg["domains"]]; comp = {d.lower() for d in cfg["competitor_domains"]}
    brand_re = re.compile(r"(?<!\w)(" + "|".join(re.escape(b) for b in cfg["brand_names"]) + r")(?!\w)", re.I)
    print(f"engines {names} | prompts {len(prompts)} | repeats {repeats}" + (" | PROBE, no snapshot" if limit else ""), flush=True)
    records, failures, dead = [], [], set()
    for p in prompts:
        for name in names:
            if name in dead: continue
            fn = E.ENGINES[name][0]
            for r in range(repeats):
                try: text, urls = fn(p["q"])
                except Exception as e:
                    failures.append({"engine": name, "prompt": p["q"], "error": str(e)[:200]}); print(f"  FAIL {name}: {str(e)[:80]}", flush=True)
                    if sum(1 for f in failures[-3:] if f["engine"] == name) >= 3: dead.add(name); print(f"  dropping {name} after 3 failures", flush=True)
                    continue
                hosts = [host(u) for u in urls if host(u)]
                rec = {"id": p["id"], "prompt": p["q"], "engine": name, "repeat": r, "brand_mentioned": bool(brand_re.search(text or "")), "domain_cited": any(h == d or h.endswith("." + d) for h in hosts for d in ours), "our_position": next((i + 1 for i, h in enumerate(hosts) if any(h == d or h.endswith("." + d) for d in ours)), None), "competitors_cited": sorted({h for h in hosts if h in comp}), "n_citations": len(hosts), "cited_hosts": hosts[:12], "answer_head": (text or "")[:400]}
                records.append(rec); print(f"  {name:<9} {'CITED' if rec['domain_cited'] else '     '} {'brand' if rec['brand_mentioned'] else '     '} n={rec['n_citations']:<2} {p['q'][:70]}", flush=True)
    if not records: sys.exit("no observations")
    def metrics(recs):
        n = len(recs); cited = sum(r["domain_cited"] for r in recs); ment = sum(r["brand_mentioned"] for r in recs); comps = sum(1 for r in recs if r["competitors_cited"])
        return {"observations": n, "citation_rate": round(cited / n, 3), "mention_rate": round(ment / n, 3), "share_of_voice": round(cited / (cited + comps), 3) if cited + comps else 0.0, "prompts_with_presence": len({r["id"] for r in recs if r["domain_cited"] or r["brand_mentioned"]})}
    m = metrics(records); per = {e: metrics([r for r in records if r["engine"] == e]) for e in names if any(r["engine"] == e for r in records)}
    hosts = collections.Counter(h for r in records for h in r["cited_hosts"]); top = hosts.most_common(15)
    today = datetime.date.today().isoformat(); prev_files = sorted(f for f in SNAP.glob("*.json") if f.stem < today); prev = json.load(open(prev_files[-1])) if prev_files else None
    if prev is None:
        q = urllib.parse.urlencode({"query": '*[_type == "pulseSnapshot" && date < $today] | order(date desc) [0]{ date, metrics }', "$today": json.dumps(today)})
        got = sanity("GET", f"/data/query/{DATASET}?{q}"); prev = (got or {}).get("result") or None
    deltas = {k: round(m[k] - prev["metrics"][k], 3) for k in ("citation_rate", "mention_rate", "share_of_voice") if prev and k in prev.get("metrics", {})} if prev else {}
    snap = {"date": today, "engines": names, "repeats": repeats, "prompt_count": len(prompts), "metrics": m, "per_engine": per, "top_hosts": top, "deltas": deltas, "failures": failures, "records": records, "note": "API-measured model layer, not the consumer UI"}
    if not limit:
        json.dump(snap, open(SNAP / f"{today}.json", "w"), indent=1)
        sanity("POST", f"/data/mutate/{DATASET}", {"mutations": [{"createOrReplace": {"_id": f"pulse-{today}", "_type": "pulseSnapshot", **{k: v for k, v in snap.items() if k != "records"}, "cited": [{"engine": r["engine"], "prompt": r["prompt"], "position": r["our_position"]} for r in records if r["domain_cited"]]}}]}) and print("snapshot saved to Sanity")
    lines = [f"# AEO pulse {today}", "", f"Engines: {', '.join(names)}. Prompts: {len(prompts)}. Observations: {m['observations']}. Measured through the APIs (model layer), not the chat apps.", "",
             f"- Citation rate (our domain in the sources): {m['citation_rate']:.0%}" + (f" ({deltas['citation_rate']:+.0%} vs {prev['date']})" if deltas else " (first run)"),
             f"- Brand mention rate: {m['mention_rate']:.0%}" + (f" ({deltas['mention_rate']:+.0%})" if deltas else ""),
             f"- Share of voice against competitor domains: {m['share_of_voice']:.0%}", f"- Prompts where we appear at all: {m['prompts_with_presence']} of {len(prompts)}", "",
             "## By engine", ""] + [f"- {e}: cited {v['citation_rate']:.0%}, mentioned {v['mention_rate']:.0%}, {v['observations']} observations" for e, v in per.items()] + ["", "## Who gets cited", ""] + [f"- {h}: {c}" for h, c in top] + ["", "## Where we were cited", ""] + ([f"- {r['engine']}: {r['prompt']} (position {r['our_position']})" for r in records if r["domain_cited"]] or ["- nowhere yet"]) + (["", "## Failures", ""] + [f"- {f['engine']}: {f['error'][:100]}" for f in failures] if failures else [])
    (HERE / "latest.md").write_text("\n".join(lines) + "\n"); print("\n".join(lines[:9]))
    if "--wa" in a and not limit:
        hook = E.env("WA_OPS_WEBHOOK")
        if hook:
            text = f"AEO pulse {today}: cited on {m['citation_rate']:.0%} of answers, brand mentioned on {m['mention_rate']:.0%}, present on {m['prompts_with_presence']} of {len(prompts)} questions" + (f" ({deltas['citation_rate']:+.0%} citations vs last run)" if deltas else " (baseline)") + f". Most cited: {', '.join(h for h, _ in top[:3])}."
            try: urllib.request.urlopen(urllib.request.Request(hook, data=json.dumps({"text": text}).encode(), method="POST", headers={"Content-Type": "application/json", "Idempotency-Key": f"pulse-{today}"}), timeout=60); print("WhatsApp digest queued")
            except Exception as e: print("WhatsApp failed", str(e)[:100])
if __name__ == "__main__": main()
