-- input_positions is a validated, temporary table of fixed weights.
-- The caller verifies the full expected date set and holding count before use.
SELECT r.session_date,
       sum(p.weight * r.simple_return) AS portfolio_return,
       count(r.simple_return) AS available_holdings
FROM returns_daily r
JOIN input_positions p USING (instrument_id)
WHERE r.session_date > ? AND r.session_date <= ?
GROUP BY r.session_date ORDER BY r.session_date;
