"""Attribution for the curated OCW presets only; no inferred URL permissions."""

import json

from .config import ROOT


def lecture_license(url):
    for preset in json.loads((ROOT / 'lecture-presets.json').read_text(encoding='utf-8')):
        if url == preset['url']:
            return dict(
                preset,
                attribution=f"{preset['creators']}. {preset['title']}. MIT OpenCourseWare, Massachusetts Institute of Technology.",
                scope='OCW materials unless otherwise marked; separately credited third-party material may have different terms.',
            )
    return None


def attributed_notes(text, video):
    license = video.get('metadata', {}).get('content_license')
    if not license or '<!-- ocw-attribution -->' in text:
        return text
    return (
        text.rstrip()
        + '\n\n<!-- ocw-attribution -->\n## Source and license\n\n'
        + (
            f"{license['attribution']}\n\n"
            f"[Original lecture]({license['url']}) · [MIT OCW source]({license['source']})\n\n"
            f"Source and these adapted notes: [{license['license_name']}]({license['license_url']}). "
            "Noncommercial use; share adaptations under the same license.\n\n"
            f"Changes: AI-generated study notes adapted from the lecture; transcript source: {video.get('method') or 'selected transcript'}. "
            "May contain errors. MIT and the instructors do not endorse these notes.\n\n"
            f"{license['scope']} [OCW terms]({license['license_evidence']}).\n"
        )
    )
