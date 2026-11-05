"""Explain self-reported risk preferences without an invented numerical risk score."""
from __future__ import annotations

import json

from scripts.audit_market_data import ROOT, sha256

DECLINE_CHOICES = {'any': 0., '5': .05, '10': .1, '20': .2, '30': .3}


def questionnaire():
    spec = json.loads((ROOT / 'config/risk_questionnaire.json').read_text())
    if spec['questionnaire_id'] != 'RQ-001' or spec['schema_version'] != 1:
        raise ValueError('Unsupported questionnaire version')
    ids = [question['id'] for question in spec['questions']]
    if len(ids) != 5 or set(ids) != {'horizon', 'liquidity', 'priority', 'reaction', 'loss_comfort'}:
        raise ValueError('RQ-001 requires five distinct questions')
    return spec


def validate_preferences(value):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {'questionnaire_id', 'answers'}:
        raise ValueError('Provide a questionnaire identity and named answers')
    spec = questionnaire()
    if value['questionnaire_id'] != spec['questionnaire_id'] or not isinstance(value['answers'], dict):
        raise ValueError('Questionnaire identity or answer format differs')
    allowed = {question['id']: {choice['value'] for choice in question['choices']}
               for question in spec['questions']}
    for key, answer in value['answers'].items():
        if key not in allowed or not isinstance(answer, str) or answer not in allowed[key]:
            raise ValueError('Unknown questionnaire question or answer')
    return value


def summarize(value, scenarios):
    validate_preferences(value)
    if value is None or not value['answers']:
        return None
    answers = dict(value['answers'])
    statements, access_notes, review_notes = [], [], []
    priority = {
        'stability': 'You place more emphasis on keeping the balance steady.',
        'balance': 'You describe a preference for balancing stability and growth.',
        'growth': 'You express a preference for growth and accept that values can fluctuate.',
        'unsure': 'Your preference between stability and growth is still uncertain.',
    }
    reaction = {
        'reduce': 'You expect to reduce your holdings after a hypothetical 20% fall.',
        'hold': 'You expect to keep your holdings while reviewing a hypothetical 20% fall.',
        'unsure': 'You are unsure how you would respond to a 20% fall.',
    }
    if 'priority' in answers:
        statements.append(priority[answers['priority']])
    if 'reaction' in answers:
        statements.append(reaction[answers['reaction']])
    if answers.get('horizon') in {'under_one', 'one_to_three'}:
        access_notes.append('You may need some of this money within three years; access needs matter separately from comfort with market swings.')
    elif answers.get('horizon') in {'three_to_five', 'over_five'}:
        access_notes.append('You describe a horizon beyond three years; this does not by itself establish your ability to absorb losses.')
    elif answers.get('horizon') == 'unsure':
        access_notes.append('The timing of your cash needs is uncertain.')
    liquidity = answers.get('liquidity')
    if liquidity == 'portfolio_needed':
        access_notes.append('You may need to sell investments to meet an unexpected expense.')
    elif liquidity == 'partly':
        access_notes.append('An unexpected expense might require part of this portfolio.')
    elif liquidity == 'other_resources':
        access_notes.append('You report having other resources for an unexpected expense.')
    elif liquidity == 'unsure':
        access_notes.append('Your flexibility to cover unexpected expenses is uncertain.')
    if answers.get('priority') == 'growth' and (
        answers.get('horizon') in {'under_one', 'one_to_three'} or liquidity in {'partly', 'portfolio_needed'}
    ):
        review_notes.append('Your willingness to accept swings and your possible need for access point in different directions. Review both rather than reducing them to one score.')
    comfort = DECLINE_CHOICES.get(answers.get('loss_comfort'))
    if answers.get('loss_comfort') == 'unsure':
        statements.append('You have not chosen a numerical loss-comfort level; none is inferred.')
    comparisons = []
    for scenario in scenarios:
        decline = max(0., -float(scenario['maximum_drawdown']))
        comparisons.append({
            'portfolio_id': scenario['id'], 'historical_maximum_decline': decline,
            'stated_decline_comfort': comfort,
            'comparison': None if comfort is None else (
                'past_decline_above_stated_comfort' if decline > comfort else 'past_decline_at_or_below_stated_comfort'),
            'illustrative_peak_balance': 1000., 'illustrative_trough_balance': 1000. * (1. - decline),
        })
    return {
        'questionnaire_id': 'RQ-001', 'questionnaire_sha256': sha256(ROOT / 'config/risk_questionnaire.json'),
        'interpretation_code_sha256': sha256(ROOT / 'scripts/risk_preferences.py'),
        'answers': answers, 'answered_questions': len(answers), 'total_questions': 5,
        'complete': len(answers) == 5, 'willingness_statements': statements,
        'access_and_capacity_notes': access_notes, 'review_notes': review_notes,
        'stated_decline_comfort': comfort, 'historical_comparisons': comparisons,
        'derived_volatility_reference': None, 'validated_risk_score': False,
        'interpretation': 'Self-reported reflection and historical comparison; not a forecast of a safe loss limit.',
    }
