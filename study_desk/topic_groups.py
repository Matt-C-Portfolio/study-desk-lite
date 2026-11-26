"""Let the model group topics; carry their teaching content forward verbatim."""


def topic_catalog(ledger):
    return [
        dict(topic, id=f'{entry["source_id"]}:T{i+1}', source_id=entry['source_id'])
        for entry in ledger
        for i, topic in enumerate(entry['topics'])
    ]


def assemble_groups(result, catalog):
    known = {topic['id']: topic for topic in catalog}
    used, topics, problems = set(), [], []
    groups = result.get('groups', [])
    if not isinstance(groups, list):
        groups = []
        problems.append('Invalid groups list; original topics retained separately')

    def append(title, ids):
        members = [known[key] for key in ids]
        unique = lambda values: list(dict.fromkeys(values))
        topics.append(
            dict(
                title=title,
                gist='\n\n'.join(unique(t['gist'] for t in members)),
                bullets=unique(v for t in members for v in t['bullets']),
                examples=unique(v for t in members for v in t['examples']),
                source_ids=unique(t['source_id'] for t in members),
                topic_ids=ids,
            )
        )

    for group in groups:
        if (
            not isinstance(group, dict)
            or not isinstance(group.get('title'), str)
            or not isinstance(group.get('topic_ids'), list)
        ):
            problems.append('Invalid group ignored; affected topics retained separately')
            continue
        ids = []
        for key in group['topic_ids']:
            if not isinstance(key, str) or key not in known:
                problems.append(f'Unknown topic ID ignored: {key}')
            elif key in used:
                problems.append(f'Repeated topic ID used only once: {key}')
            else:
                ids.append(key)
                used.add(key)
        if ids:
            append(group['title'], ids)
    for key, topic in known.items():
        if key not in used:
            problems.append(f'Omitted topic retained separately: {key}')
            append(topic['title'], [key])
    return dict(summary='', topics=topics), problems
