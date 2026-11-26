"""One background video job at a time; UI requests remain responsive."""

from pathlib import Path
import threading
import shutil

from .storage import Store
from . import config
from .video import process_video


class Processor:
    def __init__(self, database):
        self.database = database
        self.lock = threading.Lock()
        self.active = False
        store = Store(database)
        try:
            store.recover_processing()
            store.recover_runs()
            store.db.execute(
                "UPDATE graph_build SET data=data || '{\"status\":\"error\",\"detail\":\"Interrupted by server restart. Saved graph records and responses are retained.\"}'::jsonb WHERE data->>'status' IN ('running','queued')"
            )
        finally:
            store.close()

    def remove(self, video_id):
        with self.lock:
            if self.active:
                raise ValueError(
                    'Wait for the current processing job to finish before removing a lecture.'
                )
            store = Store(self.database)
            try:
                if not store.video(video_id):
                    raise ValueError('Saved video not found.')
                root = (config.DATA_DIR / 'videos').resolve()
                folder = root / str(int(video_id))
                # Never follow a redirected lecture folder outside the video store.
                if folder.resolve().parent != root or folder.is_symlink():
                    raise ValueError('Lecture data folder is outside the video store.')
                if folder.exists():
                    shutil.rmtree(folder)
                graph_root = (config.DATA_DIR / 'graphs').resolve()
                for row in store.db.execute(
                    'SELECT build_id FROM graph_input WHERE video_id=%s', (video_id,)
                ):
                    graph_folder = graph_root / f"build-{row['build_id']:04d}"
                    if graph_folder.resolve().parent != graph_root or graph_folder.is_symlink():
                        raise ValueError('Graph folder is outside the graph store.')
                    if graph_folder.exists():
                        shutil.rmtree(graph_folder)
                store.remove_video(video_id)
            finally:
                store.close()

    def start_graph(self, model, rebuild=False):
        from .graph import MODELS
        from .graph_jobs import reserve, run_queue

        if model not in (*MODELS, 'all'):
            raise ValueError('Unknown graph model.')
        with self.lock:
            if self.active:
                raise ValueError('Another job is running. Wait for it to finish.')
            store = Store(self.database)
            try:
                models = tuple(m for m in MODELS if m != 'openai') if model == 'all' else (model,)
                if 'openai' in models:
                    from .openai_model import api_key

                    if not api_key():
                        raise ValueError(
                            'OpenAI key is not configured. Local graphs can be built separately.'
                        )
                jobs = reserve(store, models, rebuild, allow_held=model == 'openai')
                if jobs:
                    self.active = True
                    threading.Thread(target=run_queue, args=(self, jobs), daemon=False).start()
                return [bid for bid, _, _ in jobs]
            finally:
                store.close()

    def start(self, video_id, action='check', model=None, seed=None, rights_confirmed=False):
        with self.lock:
            store = Store(self.database)
            try:
                video = store.video(video_id)
                if not video:
                    raise ValueError('Saved video not found.')
                if action not in {
                    'check',
                    'captions',
                    'local',
                    'generate',
                    'generate_five',
                    'generate_all_local',
                }:
                    raise ValueError('Unknown transcript action.')
                if self.active:
                    raise ValueError('Another video is processing. Please wait for it to finish.')
                if action in {'generate', 'generate_five', 'generate_all_local'}:
                    from .study_runtime import MODELS

                    if action == 'generate_all_local':
                        model, seed = '1.5B', None
                    if not isinstance(model, str) or model not in {*MODELS, 'openai'}:
                        raise ValueError('Choose 1.5B, 7B, 14B, or OpenAI.')
                    if not video['transcript_path']:
                        raise ValueError('Select a transcript in Step 2 first.')
                    if not Path(video['transcript_path']).is_file():
                        raise ValueError(
                            'Selected transcript file is missing. Choose a transcript again.'
                        )
                    if seed is not None and (type(seed) is not int or not 0 <= seed <= 2147483647):
                        raise ValueError('Seed must be an integer from 0 to 2147483647.')
                    if model == 'openai':
                        from .openai_model import api_key

                        if not api_key():
                            raise ValueError('OpenAI key is not configured on this computer.')
                        if action == 'generate_five':
                            raise ValueError(
                                'OpenAI runs one attempt at a time; seeds are local-model controls.'
                            )
                        seed = None
                    models = ['1.5B', '7B', '14B'] if action == 'generate_all_local' else [model]
                    seeds = (
                        list(range(42, 47))
                        if action in {'generate_five', 'generate_all_local'}
                        else [seed]
                    )
                    jobs = []
                    for chosen_model in models:
                        for chosen in seeds:
                            record = store.new_run(
                                video_id,
                                chosen_model,
                                dict(
                                    status='queued',
                                    detail='Queued',
                                    seed=chosen,
                                    transcript_path=video['transcript_path'],
                                    model=chosen_model,
                                    stage=0,
                                    passes=[
                                        dict(done=0, total=1, activity=0, status='pending')
                                        for _ in range(4)
                                    ],
                                ),
                            )
                            jobs.append((chosen_model, record['run_number']))
                    self.active = True
                    threading.Thread(
                        target=self._generate_queue, args=(video, jobs), daemon=False
                    ).start()
                    return True
                if action in {'captions', 'local'}:
                    version = video['versions'].get(action)
                    if version and Path(version['path']).is_file():
                        store.update_video(
                            video_id,
                            'ready',
                            'Transcript selected',
                            version['path'],
                            version['method'],
                        )
                        return False
                    if action == 'captions':
                        raise ValueError('No saved captions available. Check captions first.')
                    if video['caption_status'] == 'unchecked':
                        raise ValueError('Check captions in Step 1 first.')
                from .licensing import lecture_license

                if (
                    action in {'check', 'local'}
                    and not lecture_license(video['url'])
                    and rights_confirmed is not True
                ):
                    raise ValueError(
                        'Confirm that you own this video or have permission or a license allowing its processing before fetching captions or audio.'
                    )
                if action == 'check':
                    store.caption_status(video_id, 'checking')
                store.update_video(
                    video_id,
                    'checking' if action == 'check' else 'downloading',
                    (
                        'Checking available captions…'
                        if action == 'check'
                        else 'Starting local transcription…'
                    ),
                )
                self.active = True
                # Non-daemon: normal server shutdown lets the running job finish safely.
                threading.Thread(target=self._run, args=(video, action), daemon=False).start()
                return True
            finally:
                store.close()

    def _generate(self, video, model, numbers):
        self._generate_queue(video, [(model, number) for number in numbers])

    def _generate_queue(self, video, jobs):
        from .study_jobs import generate

        try:
            for model, number in jobs:
                store = Store(self.database)
                try:
                    record = store.run_record(video['id'], model, number)
                    record.update(status='running', detail='Preparing transcript...')
                    store.save_run(video['id'], model, record)
                finally:
                    store.close()
                try:
                    generate(self.database, video, model, number)
                except Exception as exc:
                    store = Store(self.database)
                    try:
                        record = store.run_record(video['id'], model, number)
                        record.update(status='error', detail=str(exc)[-1000:])
                        store.save_run(video['id'], model, record)
                    finally:
                        store.close()
        finally:
            with self.lock:
                self.active = False

    def _run(self, video, action):
        store = Store(self.database)
        try:
            output, method = process_video(
                video['url'],
                config.DATA_DIR / 'videos' / str(video['id']),
                lambda state, detail: store.update_video(video['id'], state, detail),
                lambda metadata: store.save_metadata(video['id'], metadata),
                mode=action,
            )
            if action == 'check':
                store.caption_status(video['id'], 'available' if output else 'unavailable')
                if output:
                    store.save_version(video['id'], 'captions', output, method)
                store.update_video(
                    video['id'],
                    'ready' if video['transcript_path'] else 'checked',
                    'Captions checked. Choose your transcript in Step 2.',
                )
            else:
                store.save_version(video['id'], 'local', output, method)
                store.update_video(
                    video['id'], 'ready', 'Local transcript selected', str(output), method
                )
        except Exception as exc:
            if action == 'check':
                store.caption_status(video['id'], 'error')
            store.update_video(video['id'], 'error', str(exc)[-1200:])
        finally:
            store.close()
            with self.lock:
                self.active = False
