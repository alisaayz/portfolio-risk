-- Coverage and usable historical input windows for the active dataset.
SELECT instrument_id, count(*) AS expected_sessions,
       count(simple_return) AS usable_daily_returns,
       count(trailing_20_ann_volatility) AS complete_20_return_windows
FROM historical_risk_inputs
GROUP BY instrument_id ORDER BY instrument_id;

-- Source-policy enforcement: only FRED should appear in accepted index context.
SELECT source_id, series_id, count(*) AS observations
FROM benchmark_context_daily GROUP BY source_id, series_id;

-- Open problems remain reviewable even though the comparator is excluded.
SELECT issue_id, observation_date, absolute_difference, tolerance, status
FROM active_quality_issues ORDER BY observation_date;
