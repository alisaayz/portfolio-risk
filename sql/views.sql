-- Select an explicit dataset; never infer the canonical version from MAX(date).
CREATE OR REPLACE VIEW accepted_prices_daily AS
SELECT d.dataset_id, p.*
FROM active_dataset a
JOIN dataset_versions d USING (dataset_id)
JOIN prices_daily p ON p.run_id = d.primary_run_id
JOIN ingestion_runs r ON r.run_id = p.run_id
JOIN source_rules s ON s.dataset_id = d.dataset_id
    AND s.source_id = r.source_id AND s.entity_id = p.instrument_id
WHERE s.purpose = 'risk_prices';

-- Calendar alignment makes both a missing day's and the next day's return NULL.
CREATE OR REPLACE VIEW returns_daily AS
WITH aligned AS (
    SELECT e.dataset_id, e.instrument_id, e.session_date, p.adjusted_close,
           lag(p.adjusted_close) OVER (
               PARTITION BY e.dataset_id, e.instrument_id ORDER BY e.session_date
           ) AS previous_adjusted_close
    FROM expected_sessions e
    JOIN active_dataset a USING (dataset_id)
    LEFT JOIN accepted_prices_daily p
        USING (dataset_id, instrument_id, session_date)
)
SELECT *, adjusted_close / previous_adjusted_close - 1 AS simple_return
FROM aligned;

-- Historical input only. A complete window means 20 valid one-session returns.
CREATE OR REPLACE VIEW historical_risk_inputs AS
SELECT *,
    CASE WHEN count(simple_return) OVER w20 = 20
         THEN sqrt(252.0 * avg(simple_return * simple_return) OVER w20)
    END AS trailing_20_ann_volatility
FROM returns_daily
WINDOW w20 AS (
    PARTITION BY dataset_id, instrument_id ORDER BY session_date
    ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
);

CREATE OR REPLACE VIEW benchmark_context_daily AS
SELECT a.dataset_id, r.source_id, b.*
FROM active_dataset a
JOIN dataset_runs dr USING (dataset_id)
JOIN benchmark_observations b ON b.run_id = dr.run_id
JOIN ingestion_runs r ON r.run_id = b.run_id
JOIN source_rules s ON s.dataset_id = a.dataset_id
    AND s.source_id = r.source_id AND s.entity_id = b.series_id
WHERE s.purpose = 'context' AND b.index_level IS NOT NULL;

CREATE OR REPLACE VIEW quarantined_benchmark_daily AS
SELECT a.dataset_id, r.source_id, b.*
FROM active_dataset a
JOIN dataset_runs dr USING (dataset_id)
JOIN benchmark_observations b ON b.run_id = dr.run_id
JOIN ingestion_runs r ON r.run_id = b.run_id
JOIN source_rules s ON s.dataset_id = a.dataset_id
    AND s.source_id = r.source_id AND s.entity_id = b.series_id
WHERE s.purpose = 'quarantine';

CREATE OR REPLACE VIEW active_quality_issues AS
SELECT q.* FROM data_quality_issues q JOIN active_dataset a USING (dataset_id);
