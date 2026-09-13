"""Archive defenses for ZIP-based formats (3MF): bombs, traversal, pathological entries."""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

MB = 1024 * 1024


class UnsafeArchiveError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ArchiveLimits:
    max_entries: int = 256
    max_uncompressed_bytes: int = 1024 * MB
    max_entry_bytes: int = 512 * MB
    max_ratio: float = 200.0  # uncompressed / compressed, per entry
    max_name_length: int = 512


DEFAULT_ARCHIVE_LIMITS = ArchiveLimits()


def validate_zip(
    path: Path, limits: ArchiveLimits = DEFAULT_ARCHIVE_LIMITS
) -> list[zipfile.ZipInfo]:
    """Return the entry list of a ZIP that is safe to expand, or raise UnsafeArchiveError."""
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
    except zipfile.BadZipFile as exc:
        raise UnsafeArchiveError(f"not a valid ZIP container: {exc}") from exc

    if len(entries) > limits.max_entries:
        raise UnsafeArchiveError(f"too many entries ({len(entries)} > {limits.max_entries})")

    total = 0
    for info in entries:
        name = info.filename
        if len(name) > limits.max_name_length:
            raise UnsafeArchiveError("entry name too long")
        pure = PurePosixPath(name.replace("\\", "/"))
        if pure.is_absolute() or ".." in pure.parts or name.startswith(("/", "\\")):
            raise UnsafeArchiveError(f"path traversal in entry {name!r}")
        if len(name) >= 2 and name[1] == ":":
            raise UnsafeArchiveError(f"drive-letter path in entry {name!r}")
        if info.file_size > limits.max_entry_bytes:
            raise UnsafeArchiveError(f"entry {name!r} too large ({info.file_size} bytes)")
        if info.compress_size > 0 and info.file_size / info.compress_size > limits.max_ratio:
            raise UnsafeArchiveError(f"suspicious compression ratio in entry {name!r}")
        if info.compress_size == 0 and info.file_size > 0:
            raise UnsafeArchiveError(f"inconsistent sizes in entry {name!r}")
        total += info.file_size
        if total > limits.max_uncompressed_bytes:
            raise UnsafeArchiveError("archive expands beyond the allowed total size")
    return entries


def read_member(path: Path, member: str, limit: int) -> bytes:
    """Read one member with a hard byte cap (the declared size is not trusted)."""
    with zipfile.ZipFile(path) as archive, archive.open(member) as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise UnsafeArchiveError(f"member {member!r} exceeds {limit} bytes")
    return data
