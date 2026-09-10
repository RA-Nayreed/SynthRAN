__all__ = ["generate", "replay", "collect"]


def generate(*args, **kwargs):
    from .trace import generate as implementation

    return implementation(*args, **kwargs)


def replay(*args, **kwargs):
    from .replay import replay as implementation

    return implementation(*args, **kwargs)


def collect(*args, **kwargs):
    from .replay import collect as implementation

    return implementation(*args, **kwargs)
