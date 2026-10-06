"""Write a zip whose members are compressed on several threads (zlib releases the GIL).

`zipfile` compresses one member at a time and can't take data that's already compressed, which made
zipping the slowest step of large builds (docs/findings/2026-10-04-large-project-and-rust.md). This
writer produces ordinary deflate members, in order, with fixed timestamps, so the output is
reproducible and readable by `zipfile`, `zipimport` and `unzip`. ZIP64 records are written only when
sizes, offsets or the member count need them.
"""

from __future__ import annotations

import hashlib
import struct
import zlib
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

DOS_TIME, DOS_DATE = 0, (0 << 9) | (1 << 5) | 1  # 1980-01-01 00:00:00, the earliest zip date
LIMIT = 0xFFFFFFFF  # from this size or offset on, ZIP64 records are needed (lowered in tests)
SENTINEL = 0xFFFFFFFF  # written in place of a value that's in the ZIP64 record instead
WINDOW = 64  # members being compressed at once: bounds memory for very large trees


@dataclass(frozen=True)
class Member:
    """One file to add: its name in the archive and how to read its bytes."""

    name: str
    read: Callable[[], bytes]
    mode: int = 0o644


@dataclass(frozen=True)
class _Packed:
    name: bytes
    flags: int
    crc: int
    size: int
    compressed: bytes
    external_attr: int
    data_hash: str  # of the uncompressed bytes, for the caller


@dataclass(frozen=True)
class _Entry:
    packed: _Packed
    offset: int


def _pack(member: Member, level: int, hasher: Callable[[bytes], str]) -> _Packed:
    data = member.read()
    compressor = zlib.compressobj(level, zlib.DEFLATED, -15)  # raw deflate, as zip stores it
    compressed = compressor.compress(data) + compressor.flush()
    try:
        name, flags = member.name.encode("ascii"), 0
    except UnicodeEncodeError:
        name, flags = member.name.encode("utf-8"), 0x800  # the "names are UTF-8" flag
    external = ((0o100000 | (0o755 if member.mode & 0o111 else 0o644)) << 16) & 0xFFFFFFFF
    return _Packed(name, flags, zlib.crc32(data), len(data), compressed, external, hasher(data))


class _HashingWriter:
    """Writes to a file and hashes everything written (the payload's sha256 is its cache key)."""

    def __init__(self, f: BinaryIO) -> None:
        self.f = f
        self.sha256 = hashlib.sha256()
        self.offset = 0

    def write(self, data: bytes) -> None:
        self.f.write(data)
        self.sha256.update(data)
        self.offset += len(data)


def write_zip(
    path: Path,
    members: Iterable[Member],
    *,
    level: int = 1,
    workers: int = 8,
    hasher: Callable[[bytes], str],
) -> tuple[str, dict[str, str]]:
    """Write `members` to `path` in the given order.

    Returns the archive's sha256 and each member's `hasher` result, keyed by member name.
    """
    entries: list[_Entry] = []
    hashes: dict[str, str] = {}
    with open(path, "wb") as f, ThreadPoolExecutor(workers) as pool:
        out = _HashingWriter(f)
        pending: list = []
        for member in members:
            pending.append(pool.submit(_pack, member, level, hasher))
            if len(pending) >= WINDOW:
                entries.append(_write_local(out, pending.pop(0).result()))
        for future in pending:
            entries.append(_write_local(out, future.result()))
        _write_central(out, entries)
        for entry in entries:
            hashes[entry.packed.name.decode("utf-8")] = entry.packed.data_hash
    return out.sha256.hexdigest(), hashes


def _write_local(out: _HashingWriter, packed: _Packed) -> _Entry:
    offset = out.offset
    big = packed.size >= LIMIT or len(packed.compressed) >= LIMIT
    extra = struct.pack("<HHQQ", 0x0001, 16, packed.size, len(packed.compressed)) if big else b""
    out.write(
        struct.pack(
            "<IHHHHHIIIHH",
            0x04034B50,  # local file header
            45 if big else 20,  # version needed: 4.5 for ZIP64, 2.0 for deflate
            packed.flags,
            8,  # deflate
            DOS_TIME,
            DOS_DATE,
            packed.crc,
            SENTINEL if big else len(packed.compressed),
            SENTINEL if big else packed.size,
            len(packed.name),
            len(extra),
        )
    )
    out.write(packed.name)
    out.write(extra)
    out.write(packed.compressed)
    return _Entry(packed, offset)


def _write_central(out: _HashingWriter, entries: list[_Entry]) -> None:
    start = out.offset
    for entry in entries:
        packed = entry.packed
        zip64 = []
        size = packed.size
        compressed = len(packed.compressed)
        offset = entry.offset
        if size >= LIMIT:
            zip64.append(size)
            size = SENTINEL
        if compressed >= LIMIT:
            zip64.append(compressed)
            compressed = SENTINEL
        if offset >= LIMIT:
            zip64.append(offset)
            offset = SENTINEL
        extra = struct.pack(f"<HH{len(zip64)}Q", 0x0001, 8 * len(zip64), *zip64) if zip64 else b""
        out.write(
            struct.pack(
                "<IHHHHHHIIIHHHHHII",
                0x02014B50,  # central directory header
                (3 << 8) | 45,  # made by: Unix, zip 4.5
                45 if zip64 else 20,
                packed.flags,
                8,
                DOS_TIME,
                DOS_DATE,
                packed.crc,
                compressed,
                size,
                len(packed.name),
                len(extra),
                0,  # comment length
                0,  # disk number
                0,  # internal attributes
                packed.external_attr,
                offset,
            )
        )
        out.write(packed.name)
        out.write(extra)
    size, count = out.offset - start, len(entries)
    if count >= 0xFFFF or start >= LIMIT or size >= LIMIT:
        zip64_end = out.offset
        out.write(
            struct.pack("<IQHHIIQQQQ", 0x06064B50, 44, 45, 45, 0, 0, count, count, size, start)
        )
        out.write(struct.pack("<IIQI", 0x07064B50, 0, zip64_end, 1))  # ZIP64 end locator
        count = min(count, 0xFFFF)
        size = SENTINEL if size >= LIMIT else size
        start = SENTINEL if start >= LIMIT else start
    out.write(struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, count, count, size, start, 0))
