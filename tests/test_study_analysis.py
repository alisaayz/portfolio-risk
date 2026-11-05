"""Regression checks for the report study decision and cohort boundaries."""
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from contextlib import closing

from scripts.study_analysis import analyze, plan_size
from scripts.study_pilot import DEFINITION, StudyPilot


class StudyAnalysisTests(unittest.TestCase):
    def test_planning_sample_size_increases_for_smaller_lift(self):
        self.assertGreater(plan_size(.6, .05)['total'], plan_size(.6, .10)['total'])
        with self.assertRaises(ValueError):
            plan_size(.95, .10)

    def test_confirmatory_analysis_filters_pilot_and_blocks_on_guardrail_or_timing(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / 'study.sqlite3'
            definition_path = root / 'definition.json'
            definition = json.loads(DEFINITION.read_text())
            definition['study_id'] = 'UX-C01'
            definition_path.write_text(json.dumps(definition))
            pilot = StudyPilot(database)
            pilot.start({'participant_id': 'f' * 32, 'consent': True})
            study = StudyPilot(database, definition_path)
            protocol_path = root / 'protocol.json'
            protocol = {
                'study_id': 'UX-C01', 'definition_sha256': hashlib.sha256(definition_path.read_bytes()).hexdigest(),
                'registered_at': '2020-01-01T00:00:00Z', 'opens_at': '2020-01-02T00:00:00Z',
                'closes_at': '2020-01-03T00:00:00Z', 'population': 'Test fixture',
                'registration_ref': 'Test fixture only', 'baseline': .4, 'minimum_lift': .2,
                'target_total': 200, 'noncompletion_margin': .05, 'critical_margin': .05,
            }
            protocol_path.write_text(json.dumps(protocol))
            self.assertEqual(analyze(database, protocol_path)['decision'], 'no_recorded_cohort')
            with closing(study.connect()) as connection, connection:
                for number in range(200):
                    variant = 'plain' if number < 100 else 'visual'
                    participant = f'{number:032x}'
                    correct = int(number < 40 or 100 <= number < 170)
                    connection.execute('INSERT INTO assignments VALUES (?, ?, ?, ?, ?, ?)',
                                       ('UX-C01', participant, variant, 1577923200, 1577923201, 'completed'))
                    connection.executemany('INSERT INTO task_answers VALUES (?, ?, ?, ?, ?, ?)',
                                           [('UX-C01', participant, q['id'], q['correct'], correct, 0)
                                            for q in definition['questions']])
            report = analyze(database, protocol_path)
            self.assertEqual(report['decision'], 'consider_default_chart')
            self.assertAlmostEqual(report['primary']['difference'], .30)
            self.assertEqual([row['assigned'] for row in report['formats']], [100, 100])
            with closing(study.connect()) as connection, connection:
                connection.execute('''UPDATE task_answers SET critical = 1
                    WHERE study_id = 'UX-C01' AND participant_id >= ? AND question_id = 'volatility_meaning' ''',
                                   (f'{170:032x}',))
            self.assertEqual(analyze(database, protocol_path)['decision'], 'keep_chart_optional')
            with closing(study.connect()) as connection, connection:
                connection.execute("UPDATE assignments SET ended_at = 1578100000 WHERE study_id = 'UX-C01'")
            with self.assertRaisesRegex(ValueError, 'registered window'):
                analyze(database, protocol_path)
            protocol['study_id'] = 'UX-P01'
            protocol_path.write_text(json.dumps(protocol))
            with self.assertRaisesRegex(ValueError, 'Pilot versions are descriptive'):
                analyze(database, protocol_path)
