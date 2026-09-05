const EXTRACTION_PROMPT = `You are reading a screenshot of a freelance-platform stats dashboard \
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
      {"label": "<short stage name, e.g. 'Sent', 'Viewed', 'Interviews', 'Hires'>", "value": <integer>}
    ],
    "breakdown": [
      {"label": "<category name from a color legend under the first/base stage's bar, e.g. 'Organic', 'Boosted'>", "percent": <best-estimate percentage 0-100 of the base bar this category's color visually occupies>}
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
- funnel.breakdown applies only when the FIRST/base stage's bar is visually split into two or more colors with a labeled legend nearby (e.g. a dot + "Organic" and a dot + "Boosted"). Estimate each category's share of that bar's width as a percentage; percentages should sum to roughly 100. If no such legend is visible, return "breakdown": [] — do not invent one.
- Completely ignore any "Boosted messages" card if present — do not extract anything from it, it has no year-based reporting.
- Every "period" field must be the literal dropdown text as shown (e.g. "2026", "Last 7 days", "Last 30 days", "Last 90 days"), never inferred or defaulted to a year.
- If a whole section (funnel, profile_metrics) isn't present in the screenshot at all, still include the key with empty/null values (period: "", stages/metrics: [], breakdown: []).
- If account_status isn't visible at all, still include the key with all values null.
- Return ONLY the JSON object.
`;

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function extractJson(text) {
  let t = text.trim();
  t = t.replace(/^```(json)?/, '').replace(/```$/, '').trim();
  const match = t.match(/\{[\s\S]*\}/);
  if (match) t = match[0];
  return JSON.parse(t);
}

async function callOpenAiVision(dataUrl, apiKey) {
  const res = await fetch('https://api.openai.com/v1/chat/completions', {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${apiKey}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      model: 'gpt-5.6-luna',
      messages: [
        {
          role: 'user',
          content: [
            { type: 'text', text: EXTRACTION_PROMPT },
            { type: 'image_url', image_url: { url: dataUrl } },
          ],
        },
      ],
      max_completion_tokens: 1100,
    }),
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`openai API error ${res.status}: ${body.slice(0, 500)}`);
  }
  const body = await res.json();
  return body.choices[0].message.content;
}

async function callOpenRouterVision(dataUrl, apiKey) {
  const res = await fetch('https://openrouter.ai/api/v1/chat/completions', {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${apiKey}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      model: 'openai/gpt-5.6-luna',
      messages: [
        {
          role: 'user',
          content: [
            { type: 'text', text: EXTRACTION_PROMPT },
            { type: 'image_url', image_url: { url: dataUrl } },
          ],
        },
      ],
      max_tokens: 1100,
    }),
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`openrouter API error ${res.status}: ${body.slice(0, 500)}`);
  }
  const body = await res.json();
  return body.choices[0].message.content;
}

function rowToEntry(row) {
  return {
    id: row.id,
    title: row.title,
    source: row.source,
    location: row.location ? JSON.parse(row.location) : null,
    funnelPeriod: row.funnel_period,
    stages: JSON.parse(row.stages || '[]'),
    breakdown: JSON.parse(row.breakdown || '[]'),
    profilePeriod: row.profile_period,
    profileTab: row.profile_tab,
    profileMetrics: JSON.parse(row.profile_metrics || '[]'),
    status: JSON.parse(row.status || '{}'),
    createdAt: row.created_at,
    ownerId: row.owner_id,
  };
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const { pathname } = url;

    if (pathname === '/api/status' && request.method === 'GET') {
      return json({ openai: !!env.OPENAI_API_KEY, openrouter: !!env.OPENROUTER_KEY });
    }

    if (pathname === '/api/extract' && request.method === 'POST') {
      try {
        const { image, provider } = await request.json();
        let text;
        if (provider === 'openrouter') {
          if (!env.OPENROUTER_KEY) throw new Error('No OPENROUTER_KEY configured');
          text = await callOpenRouterVision(image, env.OPENROUTER_KEY);
        } else {
          if (!env.OPENAI_API_KEY) throw new Error('No OPENAI_API_KEY configured');
          text = await callOpenAiVision(image, env.OPENAI_API_KEY);
        }
        const data = extractJson(text);
        return json({ ok: true, data });
      } catch (err) {
        return json({ ok: false, error: String(err.message || err) }, 502);
      }
    }

    if (pathname === '/api/entries' && request.method === 'GET') {
      const { results } = await env.DB.prepare(
        'SELECT * FROM entries ORDER BY created_at ASC'
      ).all();
      return json({ ok: true, entries: results.map(rowToEntry) });
    }

    if (pathname === '/api/entries' && request.method === 'POST') {
      const body = await request.json();
      const ownerId = body.ownerId;
      if (!ownerId) return json({ ok: false, error: 'Missing ownerId' }, 400);
      const id = crypto.randomUUID();
      const createdAt = Date.now();
      // one row per owner: replace any existing row from this browser
      await env.DB.batch([
        env.DB.prepare('DELETE FROM entries WHERE owner_id = ?').bind(ownerId),
        env.DB.prepare(
          `INSERT INTO entries
            (id, title, source, location, funnel_period, stages, breakdown, profile_period, profile_tab, profile_metrics, status, created_at, owner_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
        ).bind(
          id,
          body.title || '',
          body.source || '',
          body.location ? JSON.stringify(body.location) : null,
          body.funnelPeriod || '',
          JSON.stringify(body.stages || []),
          JSON.stringify(body.breakdown || []),
          body.profilePeriod || '',
          body.profileTab || '',
          JSON.stringify(body.profileMetrics || []),
          JSON.stringify(body.status || {}),
          createdAt,
          ownerId
        ),
      ]);
      return json({ ok: true, id, createdAt });
    }

    const entryIdMatch = pathname.match(/^\/api\/entries\/([^/]+)$/);
    if (entryIdMatch && request.method === 'DELETE') {
      const id = entryIdMatch[1];
      const ownerId = url.searchParams.get('ownerId') || '';
      const row = await env.DB.prepare('SELECT owner_id FROM entries WHERE id = ?').bind(id).first();
      if (!row) return json({ ok: false, error: 'Not found' }, 404);
      if (row.owner_id && row.owner_id !== ownerId) {
        return json({ ok: false, error: 'You can only delete your own entry' }, 403);
      }
      await env.DB.prepare('DELETE FROM entries WHERE id = ?').bind(id).run();
      return json({ ok: true });
    }

    return env.ASSETS.fetch(request);
  },
};
