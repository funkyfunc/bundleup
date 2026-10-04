from . import compute  # sibling relative import, checked for side effects only

assert compute.total([]) == 0


def render(value: int) -> str:
    return f"total={value}"
