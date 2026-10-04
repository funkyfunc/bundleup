"""Gauntlet 12: a version-specific native extension (pydantic-core)."""
from typing import List

from pydantic import BaseModel, ValidationError


class Order(BaseModel):
    id: int
    items: List[str]


def main() -> int:
    order = Order.model_validate({"id": "7", "items": ["a", "b"]})
    assert order.id == 7
    try:
        Order.model_validate({"id": "not-a-number", "items": []})
    except ValidationError:
        pass
    else:
        raise AssertionError("validation should have failed")
    print("GAUNTLET OK 12-native-per-version")
    return 0
