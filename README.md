# tandon-gems-api

Always-on API companion for the Tandon Gems website (tandon-gems.vercel.app). Express service exposing the live InterGem show schedule and the OpenAI-backed stone assistant. Public mirror of `site/api-server` + `site/data` from the main (private) repo so Render can build it; regenerate with `scripts/sync_api_mirror.sh` in the main project.

Endpoints: `GET /health`, `GET /api/shows`, `POST /api/ask {query, history?}`.
