CREATE TABLE IF NOT EXISTS ingestion_runs (
    run_id VARCHAR PRIMARY KEY,
    source_id VARCHAR NOT NULL,
    capture_id VARCHAR NOT NULL,
    manifest_sha256 VARCHAR NOT NULL,
    manifest_json VARCHAR NOT NULL,
    UNIQUE (source_id, capture_id)
);
CREATE TABLE IF NOT EXISTS instruments (
    instrument_id VARCHAR PRIMARY KEY,
    currency VARCHAR NOT NULL CHECK (currency = 'USD'),
    calendar_id VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS prices_daily (
    run_id VARCHAR NOT NULL REFERENCES ingestion_runs(run_id),
    instrument_id VARCHAR NOT NULL REFERENCES instruments(instrument_id),
    session_date DATE NOT NULL,
    open DOUBLE NOT NULL CHECK (open > 0),
    high DOUBLE NOT NULL CHECK (high > 0),
    low DOUBLE NOT NULL CHECK (low > 0),
    close DOUBLE NOT NULL CHECK (close > 0),
    adjusted_close DOUBLE NOT NULL CHECK (adjusted_close > 0),
    volume BIGINT NOT NULL CHECK (volume >= 0),
    PRIMARY KEY (run_id, instrument_id, session_date),
    CHECK (high >= greatest(open, close, low)),
    CHECK (low <= least(open, close, high))
);
CREATE TABLE IF NOT EXISTS corporate_actions (
    run_id VARCHAR NOT NULL REFERENCES ingestion_runs(run_id),
    instrument_id VARCHAR NOT NULL REFERENCES instruments(instrument_id),
    session_date DATE NOT NULL,
    action_type VARCHAR NOT NULL CHECK (action_type IN ('dividend', 'split')),
    value DOUBLE NOT NULL CHECK (value > 0),
    PRIMARY KEY (run_id, instrument_id, session_date, action_type)
);
CREATE TABLE IF NOT EXISTS benchmark_observations (
    run_id VARCHAR NOT NULL REFERENCES ingestion_runs(run_id),
    series_id VARCHAR NOT NULL,
    observation_date DATE NOT NULL,
    index_level DOUBLE CHECK (index_level IS NULL OR index_level > 0),
    units VARCHAR NOT NULL CHECK (units = 'price_index'),
    PRIMARY KEY (run_id, series_id, observation_date)
);
CREATE TABLE IF NOT EXISTS dataset_versions (
    dataset_id VARCHAR PRIMARY KEY,
    primary_run_id VARCHAR NOT NULL REFERENCES ingestion_runs(run_id),
    policy_id VARCHAR NOT NULL,
    recipe_json VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT current_timestamp
);
CREATE TABLE IF NOT EXISTS dataset_runs (
    dataset_id VARCHAR NOT NULL REFERENCES dataset_versions(dataset_id),
    run_id VARCHAR NOT NULL REFERENCES ingestion_runs(run_id),
    PRIMARY KEY (dataset_id, run_id)
);
CREATE TABLE IF NOT EXISTS source_rules (
    dataset_id VARCHAR NOT NULL REFERENCES dataset_versions(dataset_id),
    source_id VARCHAR NOT NULL,
    entity_id VARCHAR NOT NULL,
    purpose VARCHAR NOT NULL CHECK (purpose IN ('risk_prices', 'context', 'quarantine')),
    PRIMARY KEY (dataset_id, source_id, entity_id)
);
CREATE TABLE IF NOT EXISTS expected_sessions (
    dataset_id VARCHAR NOT NULL REFERENCES dataset_versions(dataset_id),
    instrument_id VARCHAR NOT NULL REFERENCES instruments(instrument_id),
    session_date DATE NOT NULL,
    PRIMARY KEY (dataset_id, instrument_id, session_date)
);
CREATE TABLE IF NOT EXISTS data_quality_issues (
    dataset_id VARCHAR NOT NULL REFERENCES dataset_versions(dataset_id),
    issue_id VARCHAR NOT NULL,
    entity_id VARCHAR NOT NULL,
    observation_date DATE NOT NULL,
    rule_id VARCHAR NOT NULL,
    observed_run_id VARCHAR NOT NULL REFERENCES ingestion_runs(run_id),
    reference_run_id VARCHAR NOT NULL REFERENCES ingestion_runs(run_id),
    observed_value DOUBLE NOT NULL,
    reference_value DOUBLE NOT NULL,
    absolute_difference DOUBLE NOT NULL,
    tolerance DOUBLE NOT NULL,
    status VARCHAR NOT NULL CHECK (status IN ('quarantined', 'resolved')),
    evidence_ref VARCHAR NOT NULL,
    resolution_note VARCHAR NOT NULL,
    PRIMARY KEY (dataset_id, issue_id)
);
CREATE TABLE IF NOT EXISTS active_dataset (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    dataset_id VARCHAR NOT NULL REFERENCES dataset_versions(dataset_id)
);
