#!/usr/bin/env python3
"""Local server for the proposal-funnel comparison tool.

Serves index.html and proxies image analysis to OpenAI (vision) so the
API key never leaves the server / touches the browser.

Run:
    python3 server.py
Then open http://localhost:8787
"""
import base64
import json
import os
import re
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(ROOT, ".env")
PORT = 8787


def load_env(path):
    env = {}
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


ENV = load_env(ENV_PATH)
OPENAI_KEY = ENV.get("OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY")
OPENROUTER_KEY = ENV.get("OPENROUTER_KEY") or ENV.get("OPENROUTER_API_KEY") or os.environ.get("OPENROUTER_API_KEY")

EXTRACTION_PROMPT = """You are reading a screenshot of a freelance-platform stats dashboard \
(like Upwork's "My Stats" page). It may show just one card (e.g. the Proposals funnel), \
or a full page/browser window with several cards: a Proposals funnel, 12-month earnings, \
Job Success Score, Top Rated / Top Rated Plus / Expert-Vetted badges, Profile metrics \
(Profile views / Invites / Impressions and clicks, with a tab bar and a year dropdown), \
and Connects balance. Some cards have a time-period dropdown (e.g. "2026", "Last 30 days", \
"Last 7 days") — always read and report that dropdown's exact visible text per card; never \
assume a period.

Extract as strict JSON, with no markdown fences and no commentary. Use this exact shape:

{
  "title": "<short overall label, e.g. account/site name plus year if there's one obvious dominant period, else empty string>",
  "source": "<the site/platform this screenshot is from, read from a visible browser URL bar, tab title, or on-page branding/logo, e.g. 'upwork.com'; empty string if no such browser chrome or branding is visible>",
  "funnel": {
    "period": "<the exact text of the Proposals card's own dropdown, e.g. '2026' or 'Last 30 days'; empty string if the Proposals card isn't visible or has no dropdown>",
    "stages": [
      {
        "label": "<short stage name, e.g. 'Sent', 'Viewed', 'Interviews', 'Hires'>",
        "value": <integer>,
        "colors_seen_in_bar": "<literally describe what you see in THIS stage's own bar/pill shape, e.g. 'light blue then dark blue' or 'solid blue, one color'>",
        "breakdown": [
          {"label": "<name of the FIRST/lighter color's category, e.g. 'Organic' — read exact names from the small legend dots below the bars if present, otherwise default to 'Organic'>", "percent": <your best estimate, 0-100, of what fraction of THIS stage's bar width, left to right, is the first color>},
          {"label": "<name of the SECOND/darker color's category, e.g. 'Boosted'>", "percent": <100 minus the first entry's percent, so the two entries always sum to 100>}
        ]
      }
    ]
  },
  "profile_metrics": {
    "period": "<exact text of the Profile metrics card's dropdown, e.g. '2026' or 'Last 90 days'; empty string if not visible>",
    "active_tab": "<whichever of 'Profile views' / 'Invites' / 'Impressions and clicks' is the currently selected tab, else empty string>",
    "metrics": [
      {"label": "<e.g. 'Impressions', 'Clicks', 'Profile views', 'Invites'>", "value": <integer>}
    ]
  },
  "account_status": {
    "job_success_score_percent": <integer 0-100, or null if not visible>,
    "top_rated": <true if a "Top Rated" badge is visible, false if account status badges are visible but this one is absent, null if you can't tell>,
    "top_rated_plus": <true/false/null, same logic for "Top Rated Plus">,
    "expert_vetted": <true/false/null, same logic for "Expert-Vetted">,
    "earnings_12mo_usd": <number, the "12-month earnings" figure with $ and commas stripped, or null if not visible>,
    "connects_balance": <integer, the current Connects balance, or null if not visible>
  }
}

Rules:
- funnel.stages must be ordered from largest/first funnel step to smallest/last step, matching the image's top-to-bottom order. If a stage's number is not visible/legible, omit that stage rather than guessing.
- For EVERY stage (Sent, Viewed, Interviews, Hires — not just the first one), look closely at that specific stage's own bar/pill shape and fill in colors_seen_in_bar honestly based on what you actually see there. Most Upwork Proposals cards render every single bar as two shades of the same color side by side (a lighter shade first, then a darker shade), even on very short/thin bars like Hires — look carefully before concluding it's solid.
- If colors_seen_in_bar for a stage describes two colors, fill in that stage's breakdown with your best-estimate percentage split; the split point is typically DIFFERENT for each stage, so estimate each one independently rather than copying the first stage's ratio.
- When a stage has two colors, its breakdown array must have exactly 2 entries (one per color) whose percents sum to 100 — never just 1 entry. Only leave a stage's breakdown as [] (zero entries) if colors_seen_in_bar for that specific stage genuinely describes one solid color.
- Completely ignore any "Boosted messages" card if present — do not extract anything from it, it has no year-based reporting.
- Every "period" field must be the literal dropdown text as shown (e.g. "2026", "Last 7 days", "Last 30 days", "Last 90 days"), never inferred or defaulted to a year.
- If a whole section (funnel, profile_metrics) isn't present in the screenshot at all, still include the key with empty/null values (period: "", stages/metrics: []).
- If account_status isn't visible at all, still include the key with all values null.
- Return ONLY the JSON object.
"""


def call_openai_vision(data_url):
    if not OPENAI_KEY:
        raise RuntimeError("No OPENAI_API_KEY found in .env")
    payload = {
        "model": "gpt-5.6-luna",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": EXTRACTION_PROMPT},
                    {"type": "image_url", "image_url": {"url": data_url, "detail": "high"}},
                ],
            }
        ],
        "max_completion_tokens": 1300,
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {OPENAI_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = json.loads(resp.read().decode())
    text = body["choices"][0]["message"]["content"]
    return text


def call_openrouter_vision(data_url):
    if not OPENROUTER_KEY:
        raise RuntimeError("No OPENROUTER_KEY found in .env")
    payload = {
        "model": "openai/gpt-5.6-luna",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": EXTRACTION_PROMPT},
                    {"type": "image_url", "image_url": {"url": data_url, "detail": "high"}},
                ],
            }
        ],
        "temperature": 0,
        "max_tokens": 1300,
    }
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {OPENROUTER_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = json.loads(resp.read().decode())
    text = body["choices"][0]["message"]["content"]
    return text


def extract_json(text):
    text = text.strip()
    text = re.sub(r"^```(json)?", "", text.strip())
    text = re.sub(r"```$", "", text.strip())
    text = text.strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        text = match.group(0)
    return json.loads(text)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send_json(self, status, obj):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            path = os.path.join(ROOT, "index.html")
            with open(path, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/status":
            self._send_json(200, {
                "openai": bool(OPENAI_KEY),
                "openrouter": bool(OPENROUTER_KEY),
            })
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path != "/api/extract":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        try:
            req = json.loads(raw)
            data_url = req["image"]
            provider = req.get("provider", "openai")
        except Exception as e:
            self._send_json(400, {"error": f"bad request: {e}"})
            return

        try:
            if provider == "openrouter":
                text = call_openrouter_vision(data_url)
            else:
                text = call_openai_vision(data_url)
            parsed = extract_json(text)
            self._send_json(200, {"ok": True, "data": parsed})
        except urllib.error.HTTPError as e:
            err_body = e.read().decode(errors="replace")
            self._send_json(502, {"ok": False, "error": f"{provider} API error {e.code}: {err_body[:500]}"})
        except Exception as e:
            self._send_json(500, {"ok": False, "error": str(e)})


if __name__ == "__main__":
    print(f"OpenAI key loaded: {bool(OPENAI_KEY)}")
    print(f"OpenRouter key loaded: {bool(OPENROUTER_KEY)}")
    print(f"Serving on http://localhost:{PORT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
