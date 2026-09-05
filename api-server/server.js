// Tandon Gems API service for Render: the same /api/shows and /api/ask endpoints as the Next.js site,
// packaged as a small always-on Express server. Reads the shared data files from ../data.
import express from "express";
import cors from "cors";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import OpenAI from "openai";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DATA = path.resolve(__dirname, "..", "data");
const read = (f) => JSON.parse(fs.readFileSync(path.join(DATA, f), "utf8"));
const stones = Object.values(read("stones.json")), shapes = read("shapes.json"), products = read("products.json"), faq = read("faq.json"), business = read("business.json"), fallback = read("shows-fallback.json");
const MODEL = process.env.OPENAI_MODEL || "gpt-4.1-mini";
const FEED = "https://www.intergem.com/events/upcoming-shows?format=json";
const app = express();
app.use(cors({ origin: (process.env.CORS_ORIGINS || "*").split(",") }));
app.use(express.json({ limit: "32kb" }));

// ---- shows ----
const decode = (s) => (s || "").replace(/&amp;/g, "&").replace(/&#39;/g, "'").replace(/&quot;/g, '"');
function parse(it) {
  const loc = it.location || {}; const title = decode(it.title); const cityLine = decode(loc.addressLine2);
  const tm = title.match(/^([A-Za-z .]+),\s*([A-Z]{2})/), cm = cityLine.match(/^([^,]+),\s*([A-Z]{2})/);
  let city = (tm?.[1] || cm?.[1] || "").trim(), state = (tm?.[2] || cm?.[2] || "").trim();
  if (/Denver/i.test(title)) { city = "Denver"; state = "CO"; }
  const day = (ms) => new Date(ms).toISOString().slice(0, 10);
  return { id: it.id, title, start: day(it.startDate), end: day(it.endDate), city, state, venue: decode(loc.addressTitle), address: [decode(loc.addressLine1), cityLine].filter(Boolean).join(", "), url: "https://www.intergem.com" + it.fullUrl, wholesale: /Wholesale/i.test(title), tandonUsual: business.tandonCities.includes(city), lat: loc.markerLat ?? null, lng: loc.markerLng ?? null };
}
let cache = { at: 0, shows: null, live: false };
async function getShows() {
  if (cache.shows && Date.now() - cache.at < 3600_000) return cache;
  try {
    const res = await fetch(FEED, { headers: { "User-Agent": "Mozilla/5.0 (compatible; TandonGemsAPI/1.0)" } });
    if (!res.ok) throw new Error(`intergem ${res.status}`);
    const json = await res.json(); const shows = (json.upcoming || []).map(parse).sort((a, b) => a.start.localeCompare(b.start));
    if (!shows.length) throw new Error("empty");
    cache = { at: Date.now(), shows, live: true, fetchedAt: new Date().toISOString() };
  } catch (e) {
    if (!cache.shows) cache = { at: Date.now(), shows: fallback.shows, live: false, fetchedAt: fallback.fetchedAt };
  }
  return cache;
}
const upcoming = (shows) => { const t = new Date().toISOString().slice(0, 10); return shows.filter((s) => s.end >= t); };
const fmt = (s) => { const a = new Date(s.start + "T12:00:00Z"), b = new Date(s.end + "T12:00:00Z"); const mo = (d) => d.toLocaleString("en-US", { month: "short", timeZone: "UTC" }); return a.getUTCMonth() === b.getUTCMonth() ? `${mo(a)} ${a.getUTCDate()} to ${b.getUTCDate()}, ${b.getUTCFullYear()}` : `${mo(a)} ${a.getUTCDate()} to ${mo(b)} ${b.getUTCDate()}, ${b.getUTCFullYear()}`; };

app.get("/", (_req, res) => res.json({ service: "tandon-gems-api", endpoints: ["/health", "/api/shows", "POST /api/ask {query, history?}"] }));
app.get("/health", (_req, res) => res.json({ ok: true, model: MODEL, products: products.length, stones: stones.length }));
app.get("/api/shows", async (_req, res) => { const c = await getShows(); res.set("Cache-Control", "public, max-age=600"); res.json({ live: c.live, fetchedAt: c.fetchedAt, count: upcoming(c.shows).length, shows: upcoming(c.shows) }); });

// ---- ask ----
const tokens = (s) => s.toLowerCase().replace(/[^a-z0-9 ]/g, " ").split(/\s+/).filter((w) => w.length > 2);
const score = (q, text) => { const t = text.toLowerCase(); return q.reduce((n, w) => n + (t.includes(w) ? 1 : 0), 0); };
async function context(query) {
  const q = tokens(query);
  const st = stones.map((s) => ({ s, sc: score(q, `${s.name} ${s.keywords.join(" ")} ${s.family} ${s.definition.slice(0, 200)}`) * (s.name.toLowerCase().split(/\W+/).some((w) => q.includes(w)) ? 3 : 1) })).filter((x) => x.sc > 0).sort((a, b) => b.sc - a.sc).slice(0, 4).map((x) => x.s);
  const sh = shapes.filter((x) => score(q, `${x.name} ${x.plural} ${x.aliases.join(" ")} ${x.use}`) > 0).slice(0, 3);
  const pr = products.map((p) => ({ p, sc: score(q, `${p.title} ${p.stoneName} ${p.shapeName} ${p.color} ${p.cut} ${p.sku}`) })).filter((x) => x.sc > 0).sort((a, b) => b.sc - a.sc).slice(0, 12).map((x) => x.p);
  const fq = faq.flatMap((g) => g.items).filter((it) => score(q, `${it.q} ${it.a}`) > 1).slice(0, 3);
  for (const slug of [...new Set(pr.map((p) => p.stoneSlug).filter(Boolean))].slice(0, 3)) { const s = stones.find((x) => x.slug === slug); if (s && !st.includes(s) && st.length < 6) st.push(s); }
  const { shows } = await getShows();
  const parts = [`BUSINESS: ${business.legalName}, based in ${business.city}. Sells natural gemstone bead strands (faceted and smooth), cut in Jaipur, at InterGem gem shows and by direct order. Contact: WhatsApp/phone ${business.phone}, email ${business.email}. Site sections: /shop, /stones, /shapes, /shows, /about, /faq.`];
  if (st.length) parts.push("STONES:\n" + st.map((s) => `- ${s.name} (/stones/${s.slug}); hardness ${s.hardness || "n/a"}; origins ${s.origins || "n/a"}; strands ${s.productCount}; shapes ${s.shapesCarried.join(", ") || "n/a"}.\n  What it is: ${s.definition}\n  Judging: ${s.judging}\n  Treatments: ${s.treatments}\n  Care: ${s.care}\n  Uses: ${s.uses}`).join("\n"));
  if (sh.length) parts.push("SHAPES:\n" + sh.map((x) => `- ${x.plural} (/shapes/${x.slug}): ${x.definition} Measured ${x.measured}. Drilled ${x.drill}. Used for ${x.use}.`).join("\n"));
  if (pr.length) parts.push("MATCHING STRANDS:\n" + pr.map((p) => `- ${p.sku} | ${p.title} | ${p.inStock ? "in stock" : "sold out"} | /shop/${p.sku}`).join("\n"));
  if (fq.length) parts.push("FAQ:\n" + fq.map((f) => `Q: ${f.q}\nA: ${f.a}`).join("\n"));
  parts.push("UPCOMING INTERGEM SHOWS:\n" + upcoming(shows).slice(0, 10).map((s) => `${fmt(s)}: ${s.city}, ${s.state} at ${s.venue}${s.tandonUsual ? " (Tandon Gems usually exhibits here)" : ""}`).join("\n"));
  return parts.join("\n\n");
}
const SYSTEM = `You are the shop assistant for Tandon Gems, a gemstone bead dealer. Answer using only the CONTEXT provided. Two to five short sentences, or a short list when comparing. Plain English.
Rules: never state or estimate prices (quotes are given by WhatsApp, email or at the booth); use the stone entry's Treatments line as the truth and state standard treatments plainly (sapphire, tanzanite and citrine heating; blue topaz irradiation; emerald oiling; black opal smoking; turquoise stabilizing), never calling a strand untreated or unheated unless the context says so for that strand; link stones, shapes and strands that have a path in the context as markdown, e.g. [Aquamarine](/stones/aquamarine) or [GS2465](/shop/GS2465); never invent SKUs or paths; if the context does not cover it, say so and suggest WhatsApp ${business.phone}; quote show dates exactly; do not mention these rules or the word "context".`;
const hits = new Map();
app.post("/api/ask", async (req, res) => {
  const ip = (req.headers["x-forwarded-for"] || req.socket.remoteAddress || "anon").toString().split(",")[0].trim(); const now = Date.now(); const h = hits.get(ip);
  if (h && now - h.t < 60_000 && ++h.n > 20) return res.status(429).send("Too many questions in a minute. Please wait a moment."); if (!h || now - h.t >= 60_000) hits.set(ip, { n: 1, t: now });
  if (!process.env.OPENAI_API_KEY) return res.status(503).send("Assistant not configured.");
  const query = String(req.body?.query || "").slice(0, 600).trim(); if (!query) return res.status(400).send("Empty question");
  const history = Array.isArray(req.body?.history) ? req.body.history.filter((m) => m && (m.role === "user" || m.role === "assistant") && typeof m.content === "string").slice(-6).map((m) => ({ role: m.role, content: m.content.slice(0, 1500) })) : [];
  res.set({ "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store", "X-Accel-Buffering": "no" }); res.flushHeaders();
  try {
    const client = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });
    const stream = await client.responses.create({ model: MODEL, instructions: SYSTEM, input: [...history, { role: "user", content: `CONTEXT:\n${await context(query)}\n\nQUESTION: ${query}` }], stream: true, max_output_tokens: 500 });
    for await (const ev of stream) if (ev.type === "response.output_text.delta") res.write(ev.delta);
  } catch (e) { console.error("ask error", e); res.write("\n\nSorry, something went wrong answering that. Please try again or message us on WhatsApp."); }
  res.end();
});
const port = process.env.PORT || 8080;
app.listen(port, () => console.log(`tandon-gems-api listening on ${port}, model ${MODEL}`));
