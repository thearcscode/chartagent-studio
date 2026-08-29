"""App-generated UUIDv7 ids (ADR-0007 D3): no database default, because the
object key needs the id before the row exists."""

import secrets
import time
import uuid


def new_id() -> uuid.UUID:
    """RFC 9562 §5.7: 48-bit unix ms, version 7, 12 + 62 random bits."""
    ms = time.time_ns() // 1_000_000
    value = (ms & 0xFFFF_FFFF_FFFF) << 80
    value |= 0x7 << 76
    value |= secrets.randbits(12) << 64
    value |= 0b10 << 62
    value |= secrets.randbits(62)
    return uuid.UUID(int=value)
