from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts.study_pilot import StudyPilot, summarize


ANSWERS = {'largest_contributor': 'AAPL', 'reference_comparison': 'above', 'volatility_meaning': 'variation'}


class StudyPilotTests(unittest.TestCase):
    def test_practice_scores_without_database_and_hides_answer_keys(self):
        with patch('scripts.study_pilot.sqlite3.connect', side_effect=AssertionError('Practice must not connect')):
            pilot = StudyPilot()
            self.assertFalse(pilot.public_definition()['recording'])
            self.assertTrue(all('correct' not in row for row in pilot.public_definition()['questions']))
            for variant in ['plain', 'visual']:
                start = pilot.start({'participant_id': 'a' * 32, 'consent': True, 'variant': variant})
                self.assertEqual(start['variant'], variant)
            receipt = pilot.finish({'participant_id': 'a' * 32, 'answers': ANSWERS})
            self.assertTrue(all(row['correct'] for row in receipt['answers']))

    def test_recorded_retries_preserve_assignment_and_participant_denominator(self):
        with TemporaryDirectory() as directory:
            database = Path(directory) / 'pilot.sqlite3'
            pilot = StudyPilot(database)
            first = {'participant_id': 'a' * 32, 'consent': True}
            second = {'participant_id': 'b' * 32, 'consent': True}
            with patch('scripts.study_pilot.secrets.choice', return_value='plain') as assign:
                self.assertEqual(pilot.start(first), pilot.start(first))
                pilot.start(second)
                self.assertEqual(assign.call_count, 2)
            submission = {'participant_id': first['participant_id'], 'answers': ANSWERS}
            self.assertEqual(pilot.finish(submission), pilot.finish(submission))
            self.assertEqual(pilot.start(first)['status'], 'completed')
            with self.assertRaisesRegex(ValueError, 'already ended'):
                pilot.finish({**submission, 'answers': None})
            pilot.finish({'participant_id': second['participant_id'], 'answers': None})
            plain, visual = summarize(database)
            self.assertEqual((plain['assigned'], plain['completed'], plain['ended_early']), (2, 1, 1))
            self.assertEqual(plain['all_correct_rate'], .5)
            self.assertIsNone(visual['all_correct_rate'])

    def test_consent_invalid_answers_and_critical_misunderstanding(self):
        with TemporaryDirectory() as directory:
            database = Path(directory) / 'pilot.sqlite3'
            pilot = StudyPilot(database)
            participant = 'c' * 32
            with self.assertRaisesRegex(ValueError, 'participate'):
                pilot.start({'participant_id': participant, 'consent': False})
            with self.assertRaisesRegex(ValueError, 'assigns'):
                pilot.start({'participant_id': participant, 'consent': True, 'variant': 'plain'})
            with self.assertRaisesRegex(ValueError, 'Start'):
                pilot.finish({'participant_id': participant, 'answers': ANSWERS})
            assigned = pilot.start({'participant_id': participant, 'consent': True})
            with self.assertRaisesRegex(ValueError, 'all three'):
                pilot.finish({'participant_id': participant, 'answers': {}})
            group = next(row for row in summarize(database) if row['variant'] == assigned['variant'])
            self.assertEqual(group['unfinished'], 1)
            wrong = {**ANSWERS, 'volatility_meaning': 'guaranteed_limit'}
            pilot.finish({'participant_id': participant, 'answers': wrong})
            group = next(row for row in summarize(database) if row['variant'] == assigned['variant'])
            self.assertEqual(group['critical_misunderstandings_among_completers'], 1)
            self.assertEqual(group['all_correct'], 0)


if __name__ == '__main__':
    unittest.main()
