"""Turn rows into one CSV line."""


def export(rows):
    return ",".join(str(r) for r in rows)
