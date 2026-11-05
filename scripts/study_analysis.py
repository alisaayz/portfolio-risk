"""Plan and analyze a closed, versioned randomized report study."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3

from scipy.stats import binomtest, fisher_exact, norm

from scripts.study_pilot import PILOT_DATABASE, summarize


ALPHA = 0.05
POWER = 0.80
SRM_ALPHA = 0.01


def plan_size(baseline, minimum_lift):
    """Equal allocation, one-sided normal approximation for two proportions."""
    treatment = baseline + minimum_lift
    if not 0 < baseline < treatment < 1:
        raise ValueError('Require 0 < baseline < baseline + minimum lift < 1')
    pooled = (baseline + treatment) / 2
    under_null = math.sqrt(2 * pooled * (1 - pooled))
    under_alternative = math.sqrt(baseline * (1 - baseline) + treatment * (1 - treatment))
    per_arm = math.ceil(((norm.isf(ALPHA) * under_null + norm.ppf(POWER) * under_alternative) / minimum_lift) ** 2)
    return {
        'method': 'equal-allocation normal approximation for the primary test',
        'control_rate_assumption': baseline, 'minimum_lift': minimum_lift,
        'one_sided_alpha': ALPHA, 'target_power': POWER,
        'per_format': per_arm, 'total': 2 * per_arm,
    }


def risk_difference(visual_events, visual_total, plain_events, plain_total):
    """Newcombe hybrid Wilson interval for visual minus plain."""
    visual = binomtest(visual_events, visual_total)
    plain = binomtest(plain_events, plain_total)
    v, p = visual.statistic, plain.statistic
    v_ci = visual.proportion_ci(confidence_level=1 - ALPHA, method='wilson')
    p_ci = plain.proportion_ci(confidence_level=1 - ALPHA, method='wilson')
    difference = v - p
    return {
        'visual': {'events': visual_events, 'assigned': visual_total, 'rate': v},
        'plain': {'events': plain_events, 'assigned': plain_total, 'rate': p},
        'difference': difference,
        'ci95': [
            max(-1, difference - math.hypot(v - v_ci.low, p_ci.high - p)),
            min(1, difference + math.hypot(v_ci.high - v, p - p_ci.low)),
        ],
    }


def read_protocol(path):
    raw = path.read_bytes()
    protocol = json.loads(raw)
    if not re.fullmatch(r'UX-C[0-9]{2,}', protocol['study_id']):
        raise ValueError('Use a separate confirmatory ID such as UX-C01. Pilot versions are descriptive.')
    if not re.fullmatch(r'[a-f0-9]{64}', protocol['definition_sha256']):
        raise ValueError('Provide the frozen report definition SHA-256')
    times = [datetime.fromisoformat(protocol[field]) for field in ('registered_at', 'opens_at', 'closes_at')]
    if any(value.utcoffset() is None for value in times) or not times[0] < times[1] < times[2]:
        raise ValueError('Use timezone-aware times with registration before opening and opening before closing')
    if not all(isinstance(protocol[key], str) and protocol[key].strip() for key in ('population', 'registration_ref')):
        raise ValueError('Describe the eligible population and cite the pre-study registration')
    design = plan_size(protocol['baseline'], protocol['minimum_lift'])
    if type(protocol['target_total']) is not int or protocol['target_total'] < design['total']:
        raise ValueError('The target must meet the approximate primary-test sample size')
    if not all(0 < protocol[key] < 1 for key in ('noncompletion_margin', 'critical_margin')):
        raise ValueError('Guardrail margins must be fractions between zero and one')
    return protocol, hashlib.sha256(raw).hexdigest(), times[1].timestamp(), times[2].timestamp()


def analyze(database, protocol_path):
    protocol, protocol_hash, opens, closes = read_protocol(protocol_path)
    report = {'study_id': protocol['study_id'], 'protocol_sha256': protocol_hash}
    if datetime.now().timestamp() < closes:
        return {**report, 'decision': 'wait_for_close'}
    if not database.is_file():
        return {**report, 'decision': 'no_recorded_cohort'}
    rows = summarize(database, study_id=protocol['study_id'], window=(opens, closes))
    if not rows:
        return {**report, 'decision': 'no_recorded_cohort'}
    if any(row['definition_sha256'] != protocol['definition_sha256'] for row in rows):
        raise ValueError('The database definition differs from the registered study definition')
    plain, visual = rows
    p_n, v_n = plain['assigned'], visual['assigned']
    report['formats'] = rows
    total = p_n + v_n
    if total == 0:
        return {**report, 'decision': 'no_recorded_cohort'}
    srm = binomtest(v_n, total, p=0.5).pvalue
    report['allocation_check'] = {'expected_visual_share': 0.5, 'p_value': srm, 'threshold': SRM_ALPHA}
    if srm < SRM_ALPHA:
        return {**report, 'decision': 'investigate_assignment_imbalance'}
    if not p_n or not v_n or total < protocol['target_total']:
        return {**report, 'decision': 'insufficient_sample'}

    p_ok, v_ok = plain['all_correct'], visual['all_correct']
    primary = risk_difference(v_ok, v_n, p_ok, p_n)
    primary['p_value'] = fisher_exact([[v_ok, v_n - v_ok], [p_ok, p_n - p_ok]], alternative='greater').pvalue
    primary['alpha'] = ALPHA
    primary['minimum_lift'] = protocol['minimum_lift']

    guardrails = {}
    for name, visual_events, plain_events, margin in [
        ('noncompletion', v_n - visual['completed'], p_n - plain['completed'], protocol['noncompletion_margin']),
        ('observed_critical_misunderstanding', visual['critical_misunderstandings_among_completers'],
         plain['critical_misunderstandings_among_completers'], protocol['critical_margin']),
    ]:
        metric = risk_difference(visual_events, v_n, plain_events, p_n)
        metric['maximum_increase'] = margin
        metric['passes'] = metric['ci95'][1] <= margin
        guardrails[name] = metric

    decision = 'keep_chart_optional'
    if (primary['p_value'] < ALPHA and primary['difference'] >= protocol['minimum_lift']
            and all(metric['passes'] for metric in guardrails.values())):
        decision = 'consider_default_chart'
    return {**report, 'primary': primary, 'guardrails': guardrails, 'decision': decision}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    plan = commands.add_parser('plan', help='Estimate a balanced primary-test sample size')
    plan.add_argument('--baseline', type=float, required=True)
    plan.add_argument('--minimum-lift', type=float, required=True)
    read = commands.add_parser('analyze', help='Read only the separately registered confirmatory cohort')
    read.add_argument('--protocol', type=Path, required=True)
    read.add_argument('--database', type=Path, default=PILOT_DATABASE)
    args = parser.parse_args()
    try:
        result = (plan_size(args.baseline, args.minimum_lift) if args.command == 'plan'
                  else analyze(args.database, args.protocol))
    except (ValueError, OSError, KeyError, TypeError, sqlite3.Error) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
