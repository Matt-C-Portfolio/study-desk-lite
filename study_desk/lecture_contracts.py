"""Study Desk teaching contracts, adapted locally for DeepSeek.
Copied from note_app/pipelines/analyzer.py and student_guide.py on 2026-10-27.
No imports from the main application. Advisory review, no repair/backfill logic.
"""


def obj(properties):
    return dict(
        type='object', properties=properties, required=list(properties), additionalProperties=False
    )


def array(item):
    return dict(type='array', items=item)


TEXT = {'type': 'string'}
STRINGS = array(TEXT)
TOPIC = dict(title=TEXT, gist=TEXT, bullets=STRINGS, examples=STRINGS)
EXTRACT_SCHEMA = obj(dict(summary=TEXT, topics=array(obj(TOPIC))))
CONSOLIDATE_SCHEMA = obj(dict(groups=array(obj(dict(title=TEXT, topic_ids=STRINGS)))))
REVIEW_SCHEMA = obj(dict(observations=STRINGS))
# Formatting revision is independent so earlier passes can be reused unchanged.
CONSOLIDATE_VERSION = 'grouped-v3'
FORMAT_VERSION = 'format-rules-v5'


def short_text(limit):
    return dict(type='string', maxLength=limit)


def bounded_array(item, maximum, minimum=0):
    return dict(type='array', items=item, minItems=minimum, maxItems=maximum)


# Unused fields are forced empty by the generation grammar, not repaired later.
EMPTY = dict(type='string', enum=[''])
BLOCK_FIELDS = {
    'paragraph': ('body',),
    'callout': ('body',),
    'bullets': ('items',),
    'steps': ('items',),
    'comparison': ('items',),
    'code': ('body', 'language', 'caption'),
    'formula': ('latex', 'caption'),
}
FIELD_SCHEMAS = dict(
    body=short_text(1400),
    items=bounded_array(short_text(700), 10, 1),
    latex=short_text(500),
    caption=short_text(500),
    language=short_text(30),
)
BLOCK = {
    'anyOf': [
        obj(
            dict(
                type=dict(type='string', enum=[kind]),
                title=short_text(90),
                **{
                    field: (
                        schema
                        if field in fields
                        else (bounded_array(TEXT, 0) if field == 'items' else EMPTY)
                    )
                    for field, schema in FIELD_SCHEMAS.items()
                },
            )
        )
        for kind, fields in BLOCK_FIELDS.items()
    ]
}
GUIDE_SCHEMA = obj(
    dict(
        sections=bounded_array(
            obj(
                dict(
                    title=short_text(90),
                    takeaway=short_text(700),
                    subsections=bounded_array(
                        obj(dict(title=short_text(90), blocks=bounded_array(BLOCK, 12, 1))), 12, 1
                    ),
                )
            ),
            1,
            1,
        )
    )
)
SCHEMAS = [EXTRACT_SCHEMA, CONSOLIDATE_SCHEMA, REVIEW_SCHEMA, GUIDE_SCHEMA]
OUTPUT_TOKENS = [6000, 16000, 3000, 12000]

EXTRACT_PROMPT = (
    'Extract only the new knowledge in one immutable, committed span of a live university lecture. Use only the supplied transcript and matched slide evidence. This is a durable evidence derivative, not the final lecture notes. Paraphrase caption language into clear notes; do not quote or preserve filler. Keep definitions, reasoning, examples, comparisons, equations, interpretations, critiques, explicit instructions, and unresolved questions that materially appear. Group semantically equivalent statements together while preserving genuinely new nuance. Treat canonical deck text as authoritative and live OCR as annotation evidence. Never infer rosters, roles, dates, course facts, or metadata from names or the meeting interface. Ignore greetings, attendance, join/leave events, recording notices, permission prompts, and tool state. Use JSON-safe <math>...</math> and <display-math>...</display-math> markers for equations, never literal backslashes. Do not impose a concept count.'
    + (
        ' No slides are supplied in Lite. Keep worked examples separately in examples, including '
        'code, results, and explanations when explicit. Leave examples empty if none are supported. '
        'Never guess on-screen code or modernize historical syntax. Use Markdown fences for code. '
        'Return summary and topics with title, gist, bullets, and examples.'
    )
)

CONSOLIDATE_PROMPT = (
    'Group the supplied extracted lecture topics by meaning. Return groups with a clear title '
    'and topic_ids only. Include every supplied topic ID exactly once. Do not rewrite, summarize, '
    'or discard content: the application carries the original details and examples forward. '
    'Merge overlapping topics such as Course Goals, Course Objectives and Skills to Acquire '
    'when they cover the same learning outcomes. Keep genuinely different concepts separate. '
    'Use topic meaning and details, not merely similar titles, to decide membership. '
    'Keep groups in order of first introduction. There is no target number of groups. '
    'Do not invent IDs. Do not return prose, bullets, examples, or source IDs.'
)

PRESENT_PROMPT = (
    'Act as a university lecture-notes editor. Format ONE supplied topic as one readable section. '
    'Use focused subsections, short explanatory paragraphs, bullets for sets, steps for processes, '
    'comparisons for contrasts, formulas for equations, and code blocks for actual code. '
    'Use only supplied content. Preserve distinct explanations, examples, results, qualifications, '
    'historical syntax and uncertainty. Merge repetition without replacing examples with generic prose. '
    'Keep the length proportional to the material: four short facts need only a short section. '
    'Do not invent advice, prerequisites, resources, examples, or assumptions. '
    'Do not include source IDs, processing commentary or bracketed editorial disclaimers. '
    'Return sections with title, takeaway and subsections containing typed blocks. '
    'Titles: at most 90 characters; takeaway: 700; block body: 1400; each item: 700; '
    'latex and caption: 500 each. Use at most 10 items per block and only as many blocks as needed. '
    'A caption is an optional complete sentence explaining a code example or formula. Aim for fewer than 200 characters; 500 is only a safety ceiling. Finish sentences well before the limit. '
    'For bullet and step blocks put list entries only in items, never duplicate them in body. Put numbered processes in a steps block, not in a caption. '
    'Paragraphs and callouts use body only. Bullets, steps and comparisons use items only, with no list markers inside items. Code uses body and language; formulas use latex. Only code and formulas may have a caption: one complete sentence, or empty. All other content fields MUST be empty. Do not repeat an idea in multiple items or blocks. '
    'Code belongs in body without Markdown fences, with its language; show output separately. '
    'Formula latex must be raw LaTeX without delimiters or XML tags. '
    'Body and items may use Markdown emphasis, but no Markdown headings. '
    'Finish the JSON once this topic is covered.'
)
REVIEW_PROMPT = (
    'Review the supplied teaching content against the transcript for possible mistakes, '
    'omissions or lost examples. Allow faithful paraphrases. Return brief observations or an '
    'empty list. This is advisory feedback, not approval or corrected study notes.'
)

# Shared, content-free formatting rules for all three model sizes.
PRESENT_PROMPT += (
    '\nUse prose as the default for connected explanations. Choose bullets for distinct parallel '
    'facts or features, steps for an ordered process, comparisons for contrasts, formulas for '
    'equations, and callouts for meaningful assumptions or pitfalls. Explain formula symbols '
    'using the supplied material. Do not force every format into every topic. '
    'Group related examples under a shared explanation. Avoid a repetitive heading-block-caption '
    'pattern. Captions must add useful explanation, not repeat a heading or say Examples of. '
    'Never put explanatory sentences in code blocks or result arrows inside executable code. '
    'Use separate prose for results, preserving historical syntax in the source. '
    'Use only the current topic DATA for subject matter, examples, and details. '
    'Write in the language of the supplied lecture.'
)

import hashlib

FORMAT_PROMPT_HASH = hashlib.sha256(PRESENT_PROMPT.encode('utf-8')).hexdigest()
