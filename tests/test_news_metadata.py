"""Synthetic metadata fixtures; no real headlines or forecast performance here."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from scripts.audit_news_metadata import inspect_archive, inspect_snapshot, timestamp


def row(extras='', organization='microsoft'):
    fields=['']*27
    fields[0]='20250127150000-1';fields[1]='20250127150000';fields[2]='1'
    fields[4]='https://example.test/story';fields[13]=organization
    fields[15]='0,0,0,0,0,0,100';fields[26]=extras
    return fields


def archive(path, rows):
    with zipfile.ZipFile(path,'w') as output:
        output.writestr('fixture.gkg.csv','\n'.join('\t'.join(fields) for fields in rows)+'\n')


class NewsMetadataTests(unittest.TestCase):
    def test_publication_time_does_not_overwrite_batch_and_later_time_is_flagged(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'sample.zip'
            archive(path,[row('<PAGE_TITLE>Synthetic fixture</PAGE_TITLE><PAGE_PRECISEPUBTIMESTAMP>20250127160000</PAGE_PRECISEPUBTIMESTAMP>')])
            result=inspect_archive(path)
            self.assertEqual(result['batch_timestamps'],['20250127150000'])
            self.assertEqual(result['counts']['precise_after_batch'],1)
            self.assertEqual(result['alias_candidate_counts'],{'MSFT':1})

    def test_missing_and_invalid_publication_fields_are_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'sample.zip'
            first=row();second=row('<PAGE_PRECISEPUBTIMESTAMP>20250230120000</PAGE_PRECISEPUBTIMESTAMP>')
            second[0]='20250127150000-2';second[4]='https://example.test/other'
            archive(path,[first,second]);result=inspect_archive(path)
            self.assertEqual(result['counts']['has_precise_publication_field'],1)
            self.assertEqual(result['counts']['invalid_precise_publication'],1)
            self.assertEqual(result['counts'].get('valid_precise_publication',0),0)

    def test_duplicate_urls_are_recorded_and_bad_schema_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'sample.zip';archive(path,[row(),row()])
            self.assertEqual(inspect_archive(path)['duplicate_document_urls'],1)
            archive(path,[row()[:-1]])
            with self.assertRaisesRegex(ValueError,'27 fields'):inspect_archive(path)

    def test_changed_saved_response_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);(folder/'response').write_text('changed')
            manifest={'run_id':'fixture','sources':{'doc':{'file':'response','sha256':hashlib.sha256(b'original').hexdigest()}}}
            (folder/'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError,'hash mismatch'):inspect_snapshot(folder)

    def test_organization_aliases_do_not_match_arbitrary_substrings(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'sample.zip';archive(path,[row(organization='microsoftish;apple orchard')])
            self.assertEqual(inspect_archive(path)['alias_candidate_counts'],{})

    def test_date_only_or_invalid_timestamp_is_not_silently_accepted(self):
        for value in ['20250127','20251327150000','20250127150000junk']:
            with self.assertRaises(ValueError):timestamp(value)


if __name__=='__main__':unittest.main()
