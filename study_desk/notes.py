"""Format lecture timestamps for the active teaching-document renderer."""


def timestamp(seconds):
    minutes, seconds = divmod(max(0, int(seconds)), 60)
    hours, minutes = divmod(minutes, 60)
    return f'{hours}:{minutes:02d}:{seconds:02d}' if hours else f'{minutes}:{seconds:02d}'
