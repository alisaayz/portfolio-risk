# Report experiment and product decision

Updated November 4, 2026.

## Product brief

**User need.** A self-directed investor wants to identify what drives portfolio risk and explain the reported figures before making a decision. The initial audience is adults who review or intend to review their own stock or ETF allocations and are unfamiliar with formal risk metrics.

**Decision.** Decide whether to display the chart by default or keep it optional. A chart could make the gap between portfolio weight and volatility contribution easier to see. It also adds visual complexity, so comprehension, completion, and misunderstanding matter more than clicks.

| Priority | Work | Evidence to proceed |
| --- | --- | --- |
| 1. Test comprehension | Observe a small facilitated pilot using the fixed demonstration report. Ask readers to explain their reasoning after submitting. | Record recurring usability issues, whether the questions distinguish understanding from copying, and where the report needs clearer labels. |
| 2. Decide whether a formal test is feasible | Revise the task if needed, set an improvement worth shipping, and estimate sample size. | A feasible recruitment plan, a frozen definition and protocol, a fixed end date, and consented recording. |
| 3. Decide on the default | Analyze the closed A/B test and review evidence against the decision rule. | Improved comprehension of practical size, with acceptable uncertainty about the guardrails. |

The pilot uses a convenience sample to discover issues. For each session, ask what the reader thought the chart showed, which fact they used, and what they would do next. Track issue, frequency, severity, and the proposed fix. Prioritize any wording that could cause readers to treat volatility as a loss limit. If access to the intended audience or the sample size is limited, keep the chart optional and use pilot feedback to improve the report.

## Analysis plan

Use one assignment per eligible participant with equal assignment probability. The control shows numerical facts. The treatment shows the same report plus a chart that switches between capital weight and share of volatility. Readers answer the same three questions with the report available. The analysis includes every assignment in the registered cohort. Early exits and unfinished sessions count as unsuccessful for the primary outcome.

| Measure | Calculation | Decision role |
| --- | --- | --- |
| Comprehension | All three correct divided by all assigned, by format | One-sided Fisher exact test at 0.05 for whether the chart improves success. Report the chart minus plain difference and a two-sided 95% Newcombe score interval. |
| Noncompletion | Ended early or unfinished divided by all assigned | The upper end of the difference interval must stay within the registered margin. |
| Observed critical misunderstanding | Selected “maximum amount this portfolio could lose” divided by all assigned | Apply the registered upper margin and review completions. A participant who left early has no observed answer, so this metric cannot determine misunderstanding among people who left. |
| Time | Median assignment-to-submission time among completers | Diagnose usability alongside completion and accuracy. |
| Assignment integrity | Two-sided exact binomial check of the 50/50 allocation | Investigate a p-value below 0.01 before interpreting outcomes. Also review the recruitment and assignment logs for repeat participation or broken exposure. |

The tool suggests considering the chart as the default only when the primary p-value is below 0.05, the estimated lift meets the registered minimum, and both guardrail upper bounds meet their margins. Otherwise the chart stays optional pending review. The minimum lift is a product threshold on the estimate. The test addresses evidence of a positive effect. The guardrail intervals are approximate, and their precision should be considered during planning.

Estimate the number of assignments before recruitment. The following example assumes 60% control success, a 10 percentage point improvement, 80% power, and a 5% one-sided significance level.

```bash
.venv/bin/python -m scripts.study_analysis plan --baseline 0.60 --minimum-lift 0.10
```

The result is **281 per format, 562 total** under a balanced normal approximation. These are planning inputs, not measured rates. Before freezing a design, check power for the exact test, random group sizes, and the precision needed for the guardrails. The planning estimate is for the primary test and does not guarantee an 80% probability of meeting the full product decision rule.

## Run the registered analysis

1. Complete the facilitated pilot under UX-P01 and review the task wording. Create a separate study definition with an ID such as `UX-C01` and freeze the corresponding app commit. The default study definition remains the pilot.
2. Before collecting confirmatory data, record the definition SHA-256, eligible population, minimum lift, sample target, guardrail margins, and fixed recruitment window in a timestamped, reviewable registration. Save its reference in a local protocol JSON. Use this field layout and fill it with the registered values.

   | Protocol field | Value |
   | --- | --- |
   | `study_id`, `definition_sha256` | Confirmatory ID and SHA-256 of the exact definition file |
   | `population`, `registration_ref` | Eligibility and a reference to the timestamped registration |
   | `registered_at`, `opens_at`, `closes_at` | ISO 8601 times with time zones, in that order |
   | `baseline`, `minimum_lift` | Planned control success and practical improvement, as fractions |
   | `target_total` | Minimum number of assignments, at least the planning estimate |
   | `noncompletion_margin`, `critical_margin` | Largest acceptable increases in the observed rates, as fractions |

3. During the registered window, run the local study with the registered definition. Use one consented session per eligible participant. End sessions and stop the server before the close. Preserve the closed database and protocol together. A shortfall at the registered close is an insufficient sample. Read primary results only after the study closes.

   ```bash
   .venv/bin/python -m scripts.serve_portfolio_app --record-pilot --port 8766 --study-definition private/UX-C01.json
   .venv/bin/python -m scripts.study_analysis analyze --protocol private/UX-C01-protocol.json
   ```

The analysis checks the study ID, definition hash, recorded timing, allocation balance, response counts, and sample minimum. It reads the SQLite database without modifying it and reports aggregate counts and metrics. The facilitator verifies that the registration was frozen before recruitment and that each participant appeared once. Those conditions require operational records outside the application. The code and decision rule have been exercised using temporary software fixtures. Real participant data and a product decision are pending.

References for experiment design and statistical methods. [Microsoft Research on experiment design](https://www.microsoft.com/en-us/research/articles/patterns-of-trustworthy-experimentation-pre-experiment-stage/) · [SciPy Fisher exact test](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.fisher_exact.html) · [Newcombe's difference-of-proportions intervals](https://doi.org/10.1002/%28SICI%291097-0258%2819980430%2917%3A8%3C873%3A%3AAID-SIM779%3E3.0.CO%3B2-I)
