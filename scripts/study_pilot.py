"""Local comprehension pilot with a fixed demo and explicit recording mode."""
from __future__ import annotations

import hashlib
import json
from contextlib import closing
import re
import secrets
import sqlite3
from statistics import median
import time

from scripts.audit_market_data import ROOT


DEFINITION = ROOT / 'config/comprehension_pilot.json'
PILOT_DATABASE = ROOT / 'private/comprehension-pilot.sqlite3'
VARIANTS = ('plain', 'visual')

SCHEMA = '''
CREATE TABLE IF NOT EXISTS experiment_definitions (
    study_id TEXT PRIMARY KEY,
    definition_sha256 TEXT NOT NULL,
    definition_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS assignments (
    study_id TEXT NOT NULL REFERENCES experiment_definitions(study_id),
    participant_id TEXT NOT NULL,
    variant TEXT NOT NULL CHECK (variant IN ('plain', 'visual')),
    started_at REAL NOT NULL,
    ended_at REAL,
    status TEXT NOT NULL CHECK (status IN ('started', 'completed', 'ended_early')),
    PRIMARY KEY (study_id, participant_id)
);
CREATE TABLE IF NOT EXISTS task_answers (
    study_id TEXT NOT NULL,
    participant_id TEXT NOT NULL,
    question_id TEXT NOT NULL,
    answer TEXT NOT NULL,
    correct INTEGER NOT NULL CHECK (correct IN (0, 1)),
    critical INTEGER NOT NULL CHECK (critical IN (0, 1)),
    PRIMARY KEY (study_id, participant_id, question_id),
    FOREIGN KEY (study_id, participant_id) REFERENCES assignments(study_id, participant_id)
);
'''


class StudyPilot:
    def __init__(self, database=None):
        self.database = database
        raw = DEFINITION.read_bytes()
        self.definition = json.loads(raw)
        self.definition_hash = hashlib.sha256(raw).hexdigest()
        self.study_id = self.definition['study_id']
        self.questions = self.definition['questions']
        if len(self.questions) != 3 or len({question['id'] for question in self.questions}) != 3:
            raise ValueError('The pilot requires three distinct questions')
        if database is not None:
            database.parent.mkdir(parents=True, exist_ok=True)
            with closing(self.connect()) as connection, connection:
                connection.executescript(SCHEMA)
                connection.execute('INSERT OR IGNORE INTO experiment_definitions VALUES (?, ?, ?)',
                                   (self.study_id, self.definition_hash, raw.decode()))
                stored = connection.execute('SELECT definition_sha256 FROM experiment_definitions WHERE study_id = ?',
                                            (self.study_id,)).fetchone()
                if stored['definition_sha256'] != self.definition_hash:
                    raise ValueError('The saved pilot uses a different definition. Create a new study version.')

    def connect(self):
        connection = sqlite3.connect(self.database, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys = ON')
        return connection

    def public_definition(self):
        return {
            'study_id': self.study_id,
            'recording': self.database is not None,
            'report': self.definition['report'],
            'questions': [{key: question[key] for key in ('id', 'prompt', 'choices')}
                          for question in self.questions],
        }

    def participant_id(self, payload):
        if not isinstance(payload, dict):
            raise ValueError('Provide a study request object')
        participant = payload.get('participant_id')
        if not isinstance(participant, str) or not re.fullmatch('[a-f0-9]{32}', participant):
            raise ValueError('Invalid anonymous participant ID')
        return participant

    def assignment(self, connection, participant):
        return connection.execute('SELECT variant, status FROM assignments WHERE study_id = ? AND participant_id = ?',
                                  (self.study_id, participant)).fetchone()

    def saved_answers(self, connection, participant):
        return dict(connection.execute('''SELECT question_id, answer FROM task_answers
            WHERE study_id = ? AND participant_id = ?''', (self.study_id, participant)).fetchall())

    def start(self, payload):
        participant = self.participant_id(payload)
        if payload.get('consent') is not True:
            raise ValueError('Choose to participate before starting')
        if self.database is None:
            if set(payload) != {'participant_id', 'consent', 'variant'} or payload['variant'] not in VARIANTS:
                raise ValueError('Choose a practice report format')
            return {'variant': payload['variant'], 'status': 'started'}
        if set(payload) != {'participant_id', 'consent'}:
            raise ValueError('The pilot assigns the report format')
        with closing(self.connect()) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            row = self.assignment(connection, participant)
            if row is None:
                variant = secrets.choice(VARIANTS)
                connection.execute('''INSERT INTO assignments
                    (study_id, participant_id, variant, started_at, status) VALUES (?, ?, ?, ?, 'started')''',
                                   (self.study_id, participant, variant, time.time()))
                return {'variant': variant, 'status': 'started'}
            receipt = dict(row)
            if row['status'] == 'completed':
                receipt['answers'] = self.score(self.saved_answers(connection, participant))
            return receipt

    def score(self, answers):
        if not isinstance(answers, dict) or set(answers) != {question['id'] for question in self.questions}:
            raise ValueError('Answer all three questions or end the session early')
        results = []
        for question in self.questions:
            answer = answers[question['id']]
            if not isinstance(answer, str) or answer not in question['choices']:
                raise ValueError('Choose one of the listed answers')
            results.append({'id': question['id'], 'answer': answer, 'correct': answer == question['correct'],
                            'critical': answer == question.get('critical_choice'),
                            'explanation': question['explanation']})
        return results

    def finish(self, payload):
        participant = self.participant_id(payload)
        if set(payload) != {'participant_id', 'answers'}:
            raise ValueError('Provide answers or explicitly end the session early')
        answers = payload['answers']
        status = 'ended_early' if answers is None else 'completed'
        results = [] if answers is None else self.score(answers)
        if self.database is not None:
            with closing(self.connect()) as connection, connection:
                connection.execute('BEGIN IMMEDIATE')
                row = self.assignment(connection, participant)
                if row is None:
                    raise ValueError('Start the pilot before submitting')
                if row['status'] != 'started':
                    saved = self.saved_answers(connection, participant)
                    if row['status'] != status or (answers is not None and saved != answers):
                        raise ValueError('This session has already ended')
                    return {'status': status, 'answers': results}
                connection.executemany('INSERT INTO task_answers VALUES (?, ?, ?, ?, ?, ?)',
                                       [(self.study_id, participant, item['id'], item['answer'],
                                         item['correct'], item['critical']) for item in results])
                connection.execute('''UPDATE assignments SET status = ?, ended_at = ?
                    WHERE study_id = ? AND participant_id = ?''', (status, time.time(), self.study_id, participant))
        return {'status': status, 'answers': results}


def summarize(database):
    """Read anonymous assignment and answer counts without modifying the pilot database."""
    with closing(sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)) as connection:
        rows = connection.execute('''
            SELECT a.study_id, a.variant, a.status, a.ended_at - a.started_at,
                   count(t.question_id), coalesce(sum(t.correct), 0), coalesce(max(t.critical), 0)
            FROM assignments AS a LEFT JOIN task_answers AS t USING (study_id, participant_id)
            GROUP BY a.study_id, a.participant_id ORDER BY a.study_id, a.variant
        ''').fetchall()
        versions = connection.execute('SELECT study_id, definition_sha256 FROM experiment_definitions ORDER BY study_id').fetchall()
    results = []
    for study_id, definition_hash in versions:
        for variant in VARIANTS:
            group = [row for row in rows if row[:2] == (study_id, variant)]
            completed = [row for row in group if row[2] == 'completed']
            successes = sum(row[4] == row[5] == 3 for row in completed)
            results.append({
                'study_id': study_id, 'definition_sha256': definition_hash, 'variant': variant,
                'assigned': len(group), 'completed': len(completed),
                'ended_early': sum(row[2] == 'ended_early' for row in group),
                'unfinished': sum(row[2] == 'started' for row in group),
                'all_correct': successes,
                'all_correct_rate': successes / len(group) if group else None,
                'critical_misunderstandings_among_completers': sum(row[6] for row in completed),
                'median_completed_seconds': median(max(0, row[3]) for row in completed) if completed else None,
            })
    return results


if __name__ == '__main__':
    if not PILOT_DATABASE.is_file():
        raise SystemExit('No local pilot database is available.')
    print(json.dumps(summarize(PILOT_DATABASE), indent=2))
