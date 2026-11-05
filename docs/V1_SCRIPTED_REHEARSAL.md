# Version 1 scripted decision rehearsal

Run November 5, 2026. This technical baseline exercises 30 scripted input paths on an isolated localhost instance of the preserved `v1.0.0` release. It uses the original DS-002 dataset through November 3, 2026. Fifteen paths cover each of the two pilot cases. They include correct settings, deliberate omissions, and invalid actions. The script checks the response, recalculated result, or validation error for each path. [Pilot cases](V1_PARTICIPANT_CASES.md) · [Version 1](https://github.com/alisaayz/portfolio-risk/tree/v1.0.0)

## Results

All 30 expected responses reproduced. The paths are deliberately selected software cases. The counts describe the test set. No participant sessions, task times, comprehension scores, or error rates were collected.

| Case | Scripted path | Runs | Verified response |
| --- | --- | ---: | --- |
| A | Correct 252-session window, lock, and target | 3 | Reached 10.60% with AAPL held at 30% and turnover within the entered cap |
| A | Turnover cap below what the target requires | 3 | Reported that the target was unreachable |
| A | AAPL lock omitted | 3 | Reached 10.60% by changing AAPL from 30.00% to 26.14% |
| A | 63- or 126-session window selected | 3 | Returned a within-target result on the selected window, while the case required 252 sessions |
| A | Target omitted | 3 | Showed lower volatility between 10.64% and 11.13%, above the case's 10.60% target |
| B | Check QQQ, EFA, and IWM on the required window and target | 3 | All were above target. No equity ETF in the screened list passed |
| B | Follow the target badge alone for XOM, IEF, and TLT | 3 | All met the numeric target. Each violated the case's equity ETF requirement |
| B | Use the 63-session window for QQQ, EFA, or IWM | 3 | Each met the target on 63 sessions and exceeded it on the required 252 sessions |
| B | Omit the 10% target for QQQ, EFA, or IWM | 3 | Each passed the default ceiling based on current volatility, despite exceeding 10% |
| B | Attempt the swap with a lock, minimum weight, or lower move limit | 3 | Rejected all three invalid swaps and reported the maximum allowed move |

The browser spot-check confirmed two cases where the displayed success message only describes the calculation. The unlocked AAPL scenario says it reaches the historical volatility target. The IEF row displays “Meets target” and offers **Compare**, even though its Treasury exposure violates the case rule. These are gaps between the decision brief and the inputs represented by Version 1. They do not show how often a person would take either path.

## Version 2 priorities supported by the rehearsal

1. **Represent the required exposure and keep-current outcome.** The screen should let users declare a permitted exposure type, separate an exposure mismatch from a volatility pass, and show a keep-current path when eligible candidates exceed the target. The Case B regression fixture should exclude the tested Treasury funds and stocks under an equity ETF requirement.
2. **Display the active target, lookback, and locks together.** Show which ceiling is in use and whether it came from the user or the current estimate. Keep active locks visible in the result. Distinguish “reduced estimated volatility” from “met the entered target.” Add regression cases for the omitted lock and target.
3. **Expose window sensitivity before presenting a candidate as robust.** Use the same candidate and comparable dates across windows. Show the 63- and 252-session estimates alongside each other when the conclusion changes. QQQ, EFA, and IWM are concrete fixtures.
4. **Carry forward explicit constraint feedback.** Preserve the unreachable-target message and rejection of moves beyond locked weights, minimums, and budgets.

The technical rehearsal can inform Version 2 implementation. The [participant readout](V1_PILOT_BASELINE.md) stays separate and pending. Human task success, confusion, and time cannot be inferred from the scripted paths.

## Reproduce

From the Version 2 checkout, point the script at a clean, prepared Version 1 working copy with the preserved warehouse and pinned virtual environment.

```bash
python3 scripts/rehearse_v1_decisions.py --v1-root "/path/to/portfolio-risk"
```

The script verifies the Git commit and warehouse hash, starts a temporary local server on port 8768, emits a JSON record of all 30 paths, and stops the server. It checks that study recording is disabled.
