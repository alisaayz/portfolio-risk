-- One row per expected instrument session. All windows end at the origin.
WITH lagged AS (
    SELECT *, lag(adjusted_close) OVER series AS previous_price,
           lag(adjusted_close, 5) OVER series AS price_5,
           lag(adjusted_close, 20) OVER series AS price_20,
           lag(adjusted_close, 60) OVER series AS price_60
    FROM modeling_prices
    WINDOW series AS (PARTITION BY dataset_id, instrument_id ORDER BY session_date)
), returns AS (
    SELECT *, adjusted_close / previous_price - 1 AS r
    FROM lagged
), measured AS (
    SELECT *, count(r) OVER w5 AS n5, count(r) OVER w20 AS n20,
           count(r) OVER w60 AS n60, count(r) OVER w252 AS n252,
           count(adjusted_close) OVER peak61 AS nprices61,
           avg(r*r) OVER w5 * 252 AS v5,
           avg(r*r) OVER w20 * 252 AS v20,
           avg(r*r) OVER w60 * 252 AS v60,
           avg(r*r) OVER w252 * 252 AS v252,
           avg(CASE WHEN r IS NULL THEN NULL WHEN r < 0 THEN r*r ELSE 0 END) OVER w20 * 252 AS down20,
           avg(CASE WHEN r IS NULL THEN NULL WHEN r < 0 THEN 1.0 ELSE 0.0 END) OVER w20 AS negative20,
           max(abs(r)) OVER w20 AS maxmove20,
           max(adjusted_close) OVER peak61 AS high61
    FROM returns
    WINDOW w5 AS (PARTITION BY dataset_id, instrument_id ORDER BY session_date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW),
           w20 AS (PARTITION BY dataset_id, instrument_id ORDER BY session_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW),
           w60 AS (PARTITION BY dataset_id, instrument_id ORDER BY session_date ROWS BETWEEN 59 PRECEDING AND CURRENT ROW),
           w252 AS (PARTITION BY dataset_id, instrument_id ORDER BY session_date ROWS BETWEEN 251 PRECEDING AND CURRENT ROW),
           peak61 AS (PARTITION BY dataset_id, instrument_id ORDER BY session_date ROWS BETWEEN 60 PRECEDING AND CURRENT ROW)
)
SELECT dataset_id, instrument_id, session_date AS origin_date,
       r AS return_1,
       CASE WHEN n5 = 5 THEN adjusted_close/price_5 - 1 END AS return_5,
       CASE WHEN n20 = 20 THEN adjusted_close/price_20 - 1 END AS return_20,
       CASE WHEN n60 = 60 THEN adjusted_close/price_60 - 1 END AS return_60,
       CASE WHEN n5 = 5 THEN v5 END AS variance_5,
       CASE WHEN n20 = 20 THEN v20 END AS variance_20,
       CASE WHEN n60 = 60 THEN v60 END AS variance_60,
       CASE WHEN n252 = 252 THEN v252 END AS variance_252,
       CASE WHEN n20 = 20 THEN down20 END AS downside_variance_20,
       CASE WHEN n20 = 20 THEN negative20 END AS negative_fraction_20,
       CASE WHEN nprices61 = 61 THEN adjusted_close/high61 - 1 END AS drawdown_60,
       CASE WHEN n20 = 20 THEN maxmove20 END AS max_abs_return_20,
       n252 = 252 AS feature_ready
FROM measured
ORDER BY instrument_id, origin_date;
