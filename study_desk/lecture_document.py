"""Small local renderer for Study Desk's typed teaching-document contract."""

from pathlib import Path
import re
import json
import copy

from .notes import timestamp
from .lecture_contracts import GUIDE_SCHEMA, BLOCK_FIELDS


def validate_topics(result):
    if not isinstance(result.get('summary'), str) or not isinstance(result.get('topics'), list):
        raise ValueError('Expected a summary and topic list.')
    for topic in result['topics']:
        if not isinstance(topic, dict) or any(
            not isinstance(topic.get(k), str) for k in ('title', 'gist')
        ):
            raise ValueError('Invalid teaching topic.')
        for key in ('bullets', 'examples'):
            if not isinstance(topic.get(key), list) or any(
                not isinstance(v, str) for v in topic[key]
            ):
                raise ValueError(f'Invalid topic {key}.')


def validate_bounds(value, schema):
    if 'anyOf' in schema and isinstance(value, dict):
        schema = next(
            (
                branch
                for branch in schema['anyOf']
                if value.get('type') in branch['properties']['type']['enum']
            ),
            {},
        )
    if isinstance(value, str) and len(value) > schema.get('maxLength', float('inf')):
        raise ValueError('Formatting field exceeded its character limit; original output saved.')
    if isinstance(value, list):
        if not schema.get('minItems', 0) <= len(value) <= schema.get('maxItems', float('inf')):
            raise ValueError('Formatting array exceeded its size limits; original output saved.')
        for item in value:
            validate_bounds(item, schema.get('items', {}))
    if isinstance(value, dict):
        for key, item in value.items():
            validate_bounds(item, schema.get('properties', {}).get(key, {}))


def validate_guide(result):
    validate_bounds(result, GUIDE_SCHEMA)
    sections = result.get('sections')
    if not isinstance(sections, list) or not sections:
        raise ValueError('No document sections returned.')
    for section in sections:
        if not isinstance(section, dict) or any(
            not isinstance(section.get(k), str) for k in ('title', 'takeaway')
        ):
            raise ValueError('Invalid document section.')
        if not isinstance(section.get('subsections'), list):
            raise ValueError('Invalid document subsections.')
        for subsection in section['subsections']:
            if (
                not isinstance(subsection, dict)
                or not isinstance(subsection.get('title'), str)
                or not isinstance(subsection.get('blocks'), list)
            ):
                raise ValueError('Invalid document subsection.')
            for block in subsection['blocks']:
                if not isinstance(block, dict) or block.get('type') not in {
                    'paragraph',
                    'bullets',
                    'steps',
                    'formula',
                    'callout',
                    'comparison',
                    'code',
                }:
                    raise ValueError('Invalid document block.')
                if any(
                    not isinstance(block.get(k), str)
                    for k in ('title', 'body', 'latex', 'caption', 'language')
                ):
                    raise ValueError('Invalid block text.')
                if not isinstance(block.get('items'), list) or any(
                    not isinstance(v, str) for v in block['items']
                ):
                    raise ValueError('Invalid block items.')
                for field in ('body', 'items', 'latex', 'caption', 'language'):
                    if field not in BLOCK_FIELDS[block['type']] and block[field]:
                        raise ValueError(
                            f'{block["type"]} blocks cannot contain {field}; original output saved.'
                        )


def fence(text, language=''):
    marker = '```'
    while marker in text:
        marker += '`'
    language = ''.join(c for c in language if c.isalnum() or c in '_+-')
    return f'{marker}{language}\n{text}\n{marker}'


def clean_display(guide):
    """Conservative presentation cleanup; never modify the saved model document."""
    result = copy.deepcopy(guide)
    changes = []

    def record(section, field, original, replacement):
        if original != replacement:
            changes.append(
                dict(section=section, field=field, original=original, displayed=replacement)
            )
        return replacement

    def key(text):
        return ' '.join(re.sub(r'[^\w\s]', '', text.casefold()).split())

    def strip_marker(text):
        return re.sub(r'^\s*(?:[-*+] |\d+[.)] )', '', text).strip()

    for section in result['sections']:
        for sub in section['subsections']:
            for block in sub['blocks']:
                kind = block['type']
                if kind in ('bullets', 'steps', 'comparison'):
                    original = dict(body=block['body'], items=block['items'])
                    body = block['body'].replace('\\n', '\n').strip()
                    rows = [r.strip() for r in body.splitlines() if r.strip()]
                    list_body = len(rows) > 1 or (
                        rows and re.match(r'^(?:[-*+] |\d+[.)] )', rows[0])
                    )
                    candidates = ([strip_marker(r) for r in rows] if list_body else []) + [
                        strip_marker(v) for v in block['items']
                    ]
                    kept = []
                    for item in candidates:
                        normalized = key(item)
                        # Only remove exact duplicates or a shorter prefix of an existing item.
                        if any(
                            normalized == key(v)
                            or (
                                len(normalized.split()) >= 4 and key(v).startswith(normalized + ' ')
                            )
                            for v in kept
                        ):
                            continue
                        kept.append(item)
                    block['items'] = kept
                    block['body'] = '' if list_body else body
                    record(section['title'], 'list', original, dict(body=block['body'], items=kept))
                caption = block['caption']
                displayed = caption
                if len(caption) == 500 and not re.search(r'[.!?][\"\']?$', caption):
                    endings = list(re.finditer(r'[.!?](?=\s|$)', caption))
                    displayed = caption[: endings[-1].end()] if endings else ''
                # Reflow explicit sequential lists without changing their wording.
                numbers = list(re.finditer(r'(?<!\S)(\d+)\.\s+', displayed))
                if len(numbers) >= 3 and [int(m[1]) for m in numbers] == list(
                    range(1, len(numbers) + 1)
                ):
                    prefix = displayed[: numbers[0].start()].strip()
                    entries = [
                        displayed[
                            m.end() : (
                                numbers[i + 1].start() if i + 1 < len(numbers) else len(displayed)
                            )
                        ].strip()
                        for i, m in enumerate(numbers)
                    ]
                    displayed = (
                        prefix + '\n\n' + '\n'.join(f'{i+1}. {v}' for i, v in enumerate(entries))
                    )
                block['caption'] = record(section['title'], 'caption', caption, displayed)
    return result, changes


def write_guide(folder, guide, chunks, cleanup=True):
    guide, changes = clean_display(guide) if cleanup else (guide, [])
    (Path(folder) / 'display-cleanup.json').write_text(
        json.dumps(changes, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    sources = {c['id']: c for c in chunks}
    lines = ['# Study notes', '', guide['overview'], '']
    for section in guide['sections']:
        lines += [
            '## ' + section['title'],
            '',
            '> ' + section['takeaway'].replace('\n', '\n> '),
            '',
        ]
        for sub in section['subsections']:
            lines += ['### ' + sub['title'], '']
            for block in sub['blocks']:
                if block['title']:
                    lines += ['**' + block['title'] + '**', '']
                kind = block['type']
                if kind == 'code':
                    lines += [fence(block['body'], block['language']), '']
                elif kind == 'callout':
                    lines += ['> ' + block['body'].replace('\n', '\n> '), '']
                elif block['body']:
                    lines += [block['body'], '']
                if kind == 'formula' and block['latex']:
                    # Keep math readable without introducing a browser math dependency.
                    lines += [fence(block['latex'], 'latex'), '']
                for i, item in enumerate(block['items']):
                    lines.append((f'{i+1}. ' if kind == 'steps' else '- ') + item)
                if block['items']:
                    lines.append('')
                if block['caption']:
                    lines += [block['caption'], '']
        refs = []
        for cid in section['source_ids']:
            source = sources.get(cid, {})
            if source.get('start') is not None and source.get('end') is not None:
                ref = timestamp(source['start']) + '–' + timestamp(source['end'])
                if ref not in refs:
                    refs.append(ref)
        if refs:
            lines += ['Lecture reference: ' + ', '.join(refs), '']
    output = Path(folder) / 'notes.md'
    output.write_text('\n'.join(lines), encoding='utf-8')
    return output
