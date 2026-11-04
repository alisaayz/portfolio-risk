# Step 1: understand a real financial ML workflow

Source review completed November 3, 2026. This walkthrough traces Microsoft's Qlib LightGBM example, then makes explicit decisions for our portfolio risk system. It does not represent an executed Qlib experiment.

## Start with our question

Given a portfolio I own or am considering, where is its risk concentrated, and can a model improve the estimate of volatility over the next 20 trading days?

We will begin with daily, USD-denominated stocks and ETFs, long-only portfolios, and end-of-day forecasts. Existing holdings and hypothetical portfolios use the same calculation engine. The initial reference universe and historical dates will be selected after checking data coverage.

## The structure worth borrowing

Qlib separates data loading and processing, time-based dataset segments, model training and inference, and recorded evaluation artifacts. Its `qrun` interface connects configured components into an execution. Our project will preserve those boundaries so an experiment can be reproduced and inspected. [Workflow documentation](https://qlib.readthedocs.io/en/latest/component/workflow.html).

```text
Observed market history
        |
Features known at time t ----------> Trained model ----------> Forecast
        |                                                        |
Future outcome, observed later ------------------------------> Evaluation
                                                                 |
                                                 Saved results and report
```

Future outcomes belong in training labels and later evaluation, never in the inputs used to issue a forecast.

## Follow the actual source

### 1. Configuration: the experiment recipe

Open the [LightGBM Alpha158 configuration](https://github.com/microsoft/qlib/blob/main/examples/benchmarks/LightGBM/workflow_config_lightgbm_Alpha158.yaml).

It points to local China-market data, selects `Alpha158` and `LGBModel`, divides history into train/validation/test periods, and configures signal and portfolio records. Its portfolio strategy is `TopkDropoutStrategy`; it is a trading experiment. The data path is an input location, not evidence that prices have been downloaded.

**Our adaptation:** an explicit configuration will name the data version, instruments, feature version, forecast horizon, split dates, baselines, model, and output locations. We will choose dates from audited coverage rather than copying the example's dates or hyperparameters.

### 2. Data handler: what the model is actually learning

The configuration does not fully reveal the target. Follow `Alpha158` into [handler.py](https://github.com/microsoft/qlib/blob/main/qlib/contrib/data/handler.py), especially `get_label_config` and `_DEFAULT_LEARN_PROCESSORS`.

The default target expression is:

```text
Ref($close, -2)/Ref($close, -1) - 1
```

At origin t, this describes the return from close t+1 to close t+2. The default learning processors include dropping unavailable labels and cross-sectional label normalization. It is not a 20-day volatility target.

In [processor.py](https://github.com/microsoft/qlib/blob/main/qlib/data/dataset/processor.py), `CSZScoreNorm` standardizes values within each date across instruments. That creates relative scores, rather than preserving a label's original units.

**Our adaptation:** retain a target that can be evaluated in annualized variance/volatility units. A transform such as log variance may be considered, but its inverse, positivity treatment, and calibration must be documented. Do not carry over cross-sectional label normalization by default.

### 3. Model: a learned mapping from features to a target

In [gbdt.py](https://github.com/microsoft/qlib/blob/main/qlib/contrib/model/gbdt.py), `LGBModel` prepares training and validation features/labels, fits LightGBM, records metrics, and predicts from inference features. Its output is a prediction per instrument-date; portfolio weights are a separate concern.

**Our adaptation:** start with a small, interpretable feature set and one gradient-boosted model. Compare it against simple forecasts before expanding complexity. We can implement these boundaries without making Qlib a required dependency.

### 4. Records: evidence about the model

In [record_temp.py](https://github.com/microsoft/qlib/blob/main/qlib/workflow/record_temp.py), signal records save predictions and labels; signal-analysis records include information-coefficient metrics; portfolio records support backtest analysis.

**Our adaptation:** save dated forecasts, realized outcomes, baseline predictions, and errors. Evaluate volatility forecasting directly before connecting predictions to portfolio reports. A successful trading backtest would answer a different question from forecast accuracy.

## Specify one row of our learning problem

| Field | Meaning in our project |
| --- | --- |
| Row key | Instrument and forecast-origin trading session t |
| Inputs X | Information available by the close at t: lagged returns, trailing variance, downside variation, drawdown |
| Target y | Annualized realized variance over sessions t+1 through t+20 |
| Model output | A positive variance estimate, displayed as annualized volatility after taking its square root |
| Baselines | Trailing 20-session variance and an exponentially weighted estimate |
| Primary comparison | MAE of annualized volatility on the same forecast origins |
| Secondary comparison | QLIKE using positive variance forecasts |
| Personal use | Combine instrument forecasts with an explicit correlation estimate to assess portfolio risk |

The target formula, using verified adjusted prices, is:

```text
r[t] = adjusted_close[t] / adjusted_close[t-1] - 1
realized_variance_next_20[t] = 252 / 20 * sum(r[t+i]^2, i=1..20)
realized_volatility_next_20[t] = sqrt(realized_variance_next_20[t])
```

This is a squared-return estimator with a 252-session annualization convention. A price level forecast, a future return forecast, and a volatility forecast are distinct targets. We are studying the third.

## Why we need three periods

- **Training:** the model learns the relationship between historical inputs and subsequent outcomes.
- **Validation:** we choose features, parameters, and the modeling procedure using later development data.
- **Final test:** after those choices are fixed, we assess the chosen procedure on untouched later data.

Because our target uses the next 20 trading sessions, nearby origins share future observations. We will remove training rows whose target windows reach the next evaluation period and use non-overlapping origins for the main comparison. A random row split would be unsuitable for our intended chronological forecasting test.

## Decisions made from this review

| Decision | Reason | Status |
| --- | --- | --- |
| Borrow Qlib's workflow organization | Separates data, learning, evaluation, and saved evidence | Chosen |
| Build a risk-specific target and evaluation | The reference's return-score task differs from our question | Chosen |
| Build the baseline before tuning ML | Establishes a useful comparison and catches calculation errors | Chosen |
| Audit prices before scaling ingestion | Adjustment meaning and history coverage determine usable returns | Next task |
| Integrate Qlib itself only if useful | Compatibility and data access remain untested | Open |

Sources above refer to the repository's changing `main` branch, reviewed on the date stated. An immutable upstream revision has not been recorded. Pin any upstream code we later execute or incorporate.

## Learning checkpoint

Before moving into implementation, be able to explain:

1. What is one row in our dataset, and what information is available at its forecast time?
2. What future outcome will the model learn to predict?
3. Why could copying the reference's target normalization give the wrong kind of output?
4. What evidence would convince us that the trained model adds value over historical variance?

The next practical step is the three-instrument real-data audit in [ACTION_PLAN.md](ACTION_PLAN.md). No data-download, installation, or model-training success is claimed by this source review.
