"""PostgreSQL records for lectures, transcripts, and experiment runs."""

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from pathlib import Path


class Store:
    def __init__(self, database):
        self.db = psycopg.connect(database, autocommit=True, row_factory=dict_row)
        with self.db.transaction():
            self.db.execute(Path(__file__).with_name('schema.sql').read_text())
            self.db.execute(Path(__file__).with_name('graph_schema.sql').read_text())

    def new_run(self, video_id, model, data):
        from datetime import datetime, timezone

        with self.db.transaction():
            self.db.execute(
                'SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (f'{video_id}:{model}',)
            )
            number = self.db.execute(
                'SELECT COALESCE(MAX(run_number),0)+1 AS number FROM study_run_history WHERE video_id=%s AND model=%s',
                (video_id, model),
            ).fetchone()['number']
            data.update(
                run_number=number, model=model, created_at=datetime.now(timezone.utc).isoformat()
            )
            self.save_run(video_id, model, data)
            return data

    def save_run(self, video_id, model, data):
        if 'run_number' not in data:
            data['run_number'] = self.runs(video_id).get(model, {}).get('run_number', 1)
        data['model'] = model
        with self.db.transaction():
            self.db.execute(
                'INSERT INTO study_run_history VALUES (%s,%s,%s,%s) ON CONFLICT(video_id,model,run_number) DO UPDATE SET data=excluded.data',
                (video_id, model, data['run_number'], Jsonb(data)),
            )
            self.db.execute(
                'INSERT INTO study_runs VALUES (%s,%s,%s) ON CONFLICT(video_id,model) DO UPDATE SET data=excluded.data',
                (video_id, model, Jsonb(data)),
            )

    def history(self, video_id):
        result = {}
        for row in self.db.execute(
            'SELECT * FROM study_run_history WHERE video_id=%s ORDER BY run_number', (video_id,)
        ):
            result.setdefault(row['model'], []).append(row['data'])
        for records in result.values():
            first = next((r['run_number'] for r in records if r['status'] == 'complete'), None)
            for record in records:
                record['graph_selected'] = record['run_number'] == first
        return result

    def runs(self, video_id):
        return {
            model: next(
                (r for r in records if r['status'] == 'running'),
                next((r for r in records if r['status'] == 'queued'), records[-1]),
            )
            for model, records in self.history(video_id).items()
        }

    def run_record(self, video_id, model, number=None):
        records = self.history(video_id).get(model, [])
        return (
            next((r for r in records if r['run_number'] == int(number)), {})
            if number
            else self.runs(video_id).get(model, {})
        )

    def recover_runs(self):
        for row in self.db.execute('SELECT * FROM study_run_history').fetchall():
            data = row['data']
            if data['status'] in {'running', 'queued'}:
                data.update(
                    status='error',
                    detail='Interrupted by server restart. Start a new run to try again.',
                )
                self.save_run(row['video_id'], row['model'], data)

    def close(self):
        self.db.close()

    def remove_video(self, video_id):
        with self.db.transaction():
            # A cross-lecture graph is invalid once one of its inputs is removed.
            self.db.execute(
                'DELETE FROM graph_build WHERE id IN (SELECT build_id FROM graph_input WHERE video_id=%s)',
                (video_id,),
            )
            for table in (
                'study_run_history',
                'study_runs',
                'transcript_versions',
                'caption_checks',
                'video_metadata',
                'video_processing',
            ):
                self.db.execute(f'DELETE FROM {table} WHERE video_id=%s', (video_id,))
            self.db.execute('DELETE FROM video_intake WHERE id=%s', (video_id,))

    def save_url(self, url):
        with self.db.transaction():
            cursor = self.db.execute(
                'INSERT INTO video_intake(url) VALUES (%s) ON CONFLICT(url) DO NOTHING', (url,)
            )
            created = cursor.rowcount == 1
        row = self.db.execute('SELECT * FROM video_intake WHERE url=%s', (url,)).fetchone()
        from .licensing import lecture_license

        license = lecture_license(url)
        if license:
            existing = self.db.execute(
                'SELECT data FROM video_metadata WHERE video_id=%s', (row['id'],)
            ).fetchone()
            metadata = existing['data'] if existing else {}
            metadata['content_license'] = license
            self.save_metadata(row['id'], metadata)
        return dict(row), created

    def urls(self):
        rows = [
            dict(r)
            for r in self.db.execute(
                '''SELECT v.*,
            COALESCE(p.state,'saved') AS state, COALESCE(p.detail,'') AS detail,
            p.transcript_path, p.method, m.data AS metadata FROM video_intake v
            LEFT JOIN video_processing p ON p.video_id=v.id
            LEFT JOIN video_metadata m ON m.video_id=v.id ORDER BY v.id DESC'''
            )
        ]
        for row in rows:
            row['metadata'] = row['metadata'] if row['metadata'] else {}
            row['versions'] = {
                r['kind']: dict(r)
                for r in self.db.execute(
                    'SELECT * FROM transcript_versions WHERE video_id=%s', (row['id'],)
                )
            }
            check = self.db.execute(
                'SELECT status FROM caption_checks WHERE video_id=%s', (row['id'],)
            ).fetchone()
            row['caption_status'] = check['status'] if check else 'unchecked'
        return rows

    def save_version(self, video_id, kind, path, method):
        with self.db.transaction():
            self.db.execute(
                'INSERT INTO transcript_versions VALUES (%s,%s,%s,%s) ON CONFLICT(video_id,kind) DO UPDATE SET path=excluded.path, method=excluded.method',
                (video_id, kind, str(path), method),
            )

    def caption_status(self, video_id, status):
        with self.db.transaction():
            self.db.execute(
                'INSERT INTO caption_checks VALUES (%s,%s) ON CONFLICT(video_id) DO UPDATE SET status=excluded.status',
                (video_id, status),
            )

    def save_metadata(self, video_id, metadata):
        with self.db.transaction():
            self.db.execute(
                'INSERT INTO video_metadata VALUES (%s,%s) ON CONFLICT(video_id) DO UPDATE SET data=excluded.data',
                (video_id, Jsonb(metadata)),
            )

    def video(self, video_id):
        return next((v for v in self.urls() if v['id'] == video_id), None)

    def update_video(self, video_id, state, detail='', transcript_path=None, method=None):
        with self.db.transaction():
            self.db.execute(
                '''INSERT INTO video_processing VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT(video_id) DO UPDATE SET state=excluded.state, detail=excluded.detail,
                transcript_path=COALESCE(excluded.transcript_path,video_processing.transcript_path),
                method=COALESCE(excluded.method,video_processing.method)''',
                (video_id, state, detail, transcript_path, method),
            )

    def recover_processing(self):
        with self.db.transaction():
            self.db.execute("UPDATE caption_checks SET status='error' WHERE status='checking'")
            self.db.execute(
                "UPDATE video_processing SET state='error', detail='Processing was interrupted. Retry to continue.' WHERE state IN ('checking','downloading','transcribing')"
            )
