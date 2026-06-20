-- Lead Generation Scraping Platform V1 schema
-- Run this in Supabase SQL Editor or via migrations.

-- Jobs table
CREATE TABLE IF NOT EXISTS jobs (
    id BIGSERIAL PRIMARY KEY,
    keyword TEXT NOT NULL,
    country TEXT NOT NULL,
    city TEXT NOT NULL,
    tile TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'completed', 'failed')),
    assigned_worker TEXT,
    claimed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    UNIQUE(keyword, country, city, tile)
);

-- Businesses table
CREATE TABLE IF NOT EXISTS businesses (
    place_id TEXT PRIMARY KEY,
    business_name TEXT,
    category TEXT,
    address TEXT,
    website TEXT,
    phone TEXT,
    rating NUMERIC,
    review_count INTEGER,
    maps_url TEXT,
    email TEXT,
    facebook TEXT,
    instagram TEXT,
    linkedin TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Workers table
CREATE TABLE IF NOT EXISTS workers (
    worker_id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'active',
    current_job BIGINT REFERENCES jobs(id),
    last_heartbeat TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Job attempts table
CREATE TABLE IF NOT EXISTS job_attempts (
    id BIGSERIAL PRIMARY KEY,
    job_id BIGINT REFERENCES jobs(id),
    worker_id TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at TIMESTAMPTZ,
    result TEXT,
    error_message TEXT
);

-- Logs table
CREATE TABLE IF NOT EXISTS logs (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    level TEXT,
    source TEXT,
    message TEXT
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_assigned_worker ON jobs(assigned_worker);
CREATE INDEX IF NOT EXISTS idx_businesses_place_id ON businesses(place_id);

-- Atomic claim function
CREATE OR REPLACE FUNCTION claim_pending_job(worker_id_param TEXT)
RETURNS SETOF jobs AS $$
BEGIN
  RETURN QUERY
    UPDATE jobs
    SET
      status = 'running',
      assigned_worker = worker_id_param,
      claimed_at = NOW()
    WHERE id = (
      SELECT id
      FROM jobs
      WHERE status = 'pending'
      ORDER BY created_at
      LIMIT 1
      FOR UPDATE SKIP LOCKED
    )
    RETURNING *;
END;
$$ LANGUAGE plpgsql;

-- Enable Row Level Security if using Supabase Auth and policies
ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE businesses ENABLE ROW LEVEL SECURITY;
ALTER TABLE workers ENABLE ROW LEVEL SECURITY;
ALTER TABLE job_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE logs ENABLE ROW LEVEL SECURITY;

-- Example RLS policies (customize for your auth model)
-- Allow authenticated users to read pending jobs.
-- CREATE POLICY "workers_read_pending_jobs" ON jobs
--     FOR SELECT TO authenticated
--     USING (status = 'pending');

-- Allow workers to update their own running job records.
-- CREATE POLICY "workers_manage_own_jobs" ON jobs
--     FOR UPDATE TO authenticated
--     USING (assigned_worker = current_setting('app.current_worker', true));

-- Allow insert-only access for businesses.
-- CREATE POLICY "insert_businesses" ON businesses
--     FOR INSERT TO authenticated
--     WITH CHECK (true);
