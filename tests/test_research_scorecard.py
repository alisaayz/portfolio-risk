import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts.serve_portfolio_app import research_scorecard


def fixture(root):
    recipe = {'fixture': 'development-scorecard'}
    identity = hashlib.sha256(json.dumps(recipe, sort_keys=True).encode()).hexdigest()
    folder = root / identity
    folder.mkdir()
    metrics = [{'year': year, 'evaluation_mode': 'primary', 'method': method,
                'volatility_mae_pp': 1., 'variance_qlike': -1.}
               for year in [2023, 2024, 2025] for method in ['model', 'ewma', 'trailing_20']]
    summary = {'recipe': recipe, 'experiment_id': identity, 'selected_model': 'model',
               'selected_ewma': 'ewma', 'final_test_scores_computed': False, 'overall_metrics': metrics}
    (folder / 'summary.json').write_text(json.dumps(summary))
    manifest = {'experiment_id': identity,
                'outputs': {'summary.json': hashlib.sha256((folder / 'summary.json').read_bytes()).hexdigest()}}
    (folder / 'manifest.json').write_text(json.dumps(manifest))
    return folder, summary


class ResearchScorecardTests(unittest.TestCase):
    def test_development_scores_are_exposed_without_significance_or_user_benefit_claims(self):
        with tempfile.TemporaryDirectory() as directory:
            folder, _ = fixture(Path(directory))
            result = research_scorecard(folder)
            self.assertEqual(len(result['metrics']), 9)
            self.assertFalse(result['statistical_significance_established'])
            self.assertFalse(result['user_experiment_performed'])

    def test_modified_summary_is_rejected_instead_of_displaying_unverified_numbers(self):
        with tempfile.TemporaryDirectory() as directory:
            folder, summary = fixture(Path(directory))
            summary['overall_metrics'][0]['volatility_mae_pp'] = 0.
            (folder / 'summary.json').write_text(json.dumps(summary))
            with self.assertRaisesRegex(ValueError, 'hash'):
                research_scorecard(folder)

    def test_unbuilt_experiment_does_not_invent_metric_values(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(research_scorecard(Path(directory)))


if __name__ == '__main__':
    unittest.main()
