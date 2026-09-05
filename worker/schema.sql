CREATE TABLE IF NOT EXISTS entries (
  id TEXT PRIMARY KEY,
  title TEXT,
  source TEXT,
  location TEXT,
  funnel_period TEXT,
  stages TEXT,
  breakdown TEXT,
  profile_period TEXT,
  profile_tab TEXT,
  profile_metrics TEXT,
  status TEXT,
  created_at INTEGER,
  owner_id TEXT
);
