type Pair[T] = tuple[T, T]


def first[T](pair: Pair[T]) -> T:
    return pair[0]
