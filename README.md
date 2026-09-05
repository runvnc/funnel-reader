# Funnel Reader

A tool for reading freelance-platform stats screenshots (like Upwork's "My Stats" page) with a
vision model and building a comparison table across multiple screenshots/people — funnel counts,
conversion rates, Organic/Boosted traffic split, profile metrics, and account status (Top Rated,
Top Rated Plus, Expert-Vetted, Job Success Score, earnings, Connects), with filtering and
per-browser ownership so each person can only edit/delete their own row.

Two ways to run it:

## 1. Local (Python, single user)

```
cd .
cp .env.example .env   # fill in your keys
python3 server.py
```

Open http://localhost:8787. Entries live in memory only (reset on restart).

Requires `OPENAI_API_KEY` and/or `OPENROUTER_KEY` in `.env`.

## 2. Cloudflare Worker (hosted, persistent, multi-user)

See `worker/`. Uses a D1 database for persistent storage and Wrangler secrets for the API keys.

```
cd worker
npx wrangler d1 create funnel-reader-db   # then put the database_id into wrangler.toml
npx wrangler d1 execute funnel-reader-db --remote --file=./schema.sql
npx wrangler secret put OPENAI_API_KEY
npx wrangler secret put OPENROUTER_KEY
npx wrangler deploy
```

Each browser gets an anonymous ID (localStorage) and can only edit/delete its own saved row;
saving again replaces your previous row rather than adding a duplicate.
