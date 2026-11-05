import copy
import unittest

from scripts.risk_preferences import questionnaire, summarize, validate_preferences
from scripts.serve_portfolio_app import assess, validate_request
from tests.test_portfolio_app import payload, registry
from tests.test_portfolio_baseline import database


def responses(**answers):
    return {'questionnaire_id': 'RQ-001', 'answers': answers}


class RiskPreferenceTests(unittest.TestCase):
    def test_questionnaire_has_five_original_questions_with_explicit_uncertainty(self):
        spec = questionnaire()
        self.assertEqual(len(spec['questions']), 5)
        for question in spec['questions']:
            self.assertIn('unsure', {choice['value'] for choice in question['choices']})

    def test_answers_are_validated_without_accepting_arbitrary_profile_fields(self):
        for value in [{'questionnaire_id': 'different', 'answers': {}},
                      responses(horizon='twenty_days'), responses(age='30'),
                      responses(loss_comfort=20), {'questionnaire_id': 'RQ-001', 'answers': {}, 'income': 1000}]:
            with self.assertRaises(ValueError):
                validate_preferences(value)

    def test_unknown_answers_do_not_produce_a_volatility_target_or_loss_threshold(self):
        value = responses(**{q['id']: 'unsure' for q in questionnaire()['questions']})
        result = summarize(value, [{'id': 'p', 'maximum_drawdown': -.25}])
        self.assertTrue(result['complete'])
        self.assertIsNone(result['stated_decline_comfort'])
        self.assertIsNone(result['derived_volatility_reference'])
        self.assertFalse(result['validated_risk_score'])
        self.assertIsNone(result['historical_comparisons'][0]['comparison'])

    def test_partial_answers_are_reported_as_partial(self):
        result = summarize(responses(priority='stability'), [{'id': 'p', 'maximum_drawdown': -.1}])
        self.assertEqual(result['answered_questions'], 1)
        self.assertFalse(result['complete'])
        self.assertTrue(result['willingness_statements'])
        self.assertEqual(result['access_and_capacity_notes'], [])

    def test_willingness_and_access_needs_are_kept_separate(self):
        value = responses(priority='growth', horizon='under_one', liquidity='portfolio_needed')
        result = summarize(value, [{'id': 'p', 'maximum_drawdown': -.2}])
        self.assertIn('growth', result['willingness_statements'][0])
        self.assertTrue(result['access_and_capacity_notes'])
        self.assertTrue(result['review_notes'])
        self.assertIsNone(result['derived_volatility_reference'])

    def test_only_explicit_decline_choices_control_historical_comparisons(self):
        scenarios = [{'id': 'larger_drop', 'maximum_drawdown': -.25},
                     {'id': 'smaller_drop', 'maximum_drawdown': -.1}]
        result = summarize(responses(loss_comfort='20'), scenarios)
        large, small = result['historical_comparisons']
        self.assertEqual(result['stated_decline_comfort'], .2)
        self.assertEqual(large['comparison'], 'past_decline_above_stated_comfort')
        self.assertEqual(small['comparison'], 'past_decline_at_or_below_stated_comfort')
        self.assertEqual(large['illustrative_trough_balance'], 750.)

    def test_zero_loss_comfort_is_valid_and_is_not_treated_as_missing(self):
        result = summarize(responses(loss_comfort='any'), [{'id': 'p', 'maximum_drawdown': -.01}])
        self.assertEqual(result['stated_decline_comfort'], 0.)
        self.assertEqual(result['historical_comparisons'][0]['comparison'], 'past_decline_above_stated_comfort')

    def test_no_answers_produce_no_profile(self):
        self.assertIsNone(summarize(None, []))
        self.assertIsNone(summarize(responses(), []))

    def test_questionnaire_does_not_change_risk_calculations_or_manual_reference(self):
        request = payload()
        request['volatility_reference'] = .12
        with database() as connection:
            before = assess(connection, request, registry())
            request['risk_preferences'] = responses(priority='stability', loss_comfort='10')
            after = assess(connection, request, registry())
        self.assertEqual(before['analysis'], after['analysis'])
        self.assertEqual(before['reference_comparisons'], after['reference_comparisons'])
        self.assertIsNotNone(after['risk_preferences'])
        self.assertIsNone(after['risk_preferences']['derived_volatility_reference'])

    def test_one_portfolio_and_optional_comparison_use_the_same_primary_risk(self):
        single = payload()
        comparison = copy.deepcopy(single)
        extra = copy.deepcopy(comparison['configuration']['portfolios'][0])
        extra.update(id='alternative', name='Alternative')
        comparison['configuration']['portfolios'].append(extra)
        with database() as connection:
            first = assess(connection, single, registry())
            second = assess(connection, comparison, registry())
        self.assertEqual(len(first['analysis']['scenarios']), 1)
        self.assertEqual(len(second['analysis']['scenarios']), 2)
        self.assertEqual(first['analysis']['scenarios'][0]['annualized_sample_volatility'],
                         second['analysis']['scenarios'][0]['annualized_sample_volatility'])
        self.assertEqual(len(first['historical_scenarios']), 1)
        self.assertEqual(len(second['historical_scenarios']), 2)


if __name__ == '__main__':
    unittest.main()
