-- Clip before window calculations: final-test outcomes never enter this query.
WITH development_prices AS (
    SELECT * FROM modeling_prices WHERE session_date < ?
), returns AS (
    SELECT *, adjusted_close / lag(adjusted_close) OVER (
        PARTITION BY dataset_id, instrument_id ORDER BY session_date
    ) - 1 AS r
    FROM development_prices
), measured AS (
    SELECT dataset_id, instrument_id, session_date AS origin_date,
           lead(session_date, 20) OVER series AS observed_target_end,
           count(r) OVER future20 AS valid_future_returns,
           avg(r*r) OVER future20 * 252 AS future_variance
    FROM returns
    WINDOW series AS (PARTITION BY dataset_id, instrument_id ORDER BY session_date),
           future20 AS (PARTITION BY dataset_id, instrument_id ORDER BY session_date ROWS BETWEEN 1 FOLLOWING AND 20 FOLLOWING)
)
SELECT dataset_id, instrument_id, origin_date, observed_target_end,
       valid_future_returns,
       CASE WHEN valid_future_returns = 20 THEN future_variance END AS target_variance,
       CASE WHEN valid_future_returns = 20 THEN sqrt(future_variance) END AS target_volatility
FROM measured
ORDER BY instrument_id, origin_date;
