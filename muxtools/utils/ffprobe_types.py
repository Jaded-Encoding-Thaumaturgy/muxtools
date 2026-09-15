from __future__ import annotations

try:
    from ffmpeg_core.ffprobe.schema import ffprobeType, formatType, streamType, tagsType
except ImportError:  # typed-ffmpeg-compatible < 4.0
    from typed_ffmpeg.ffprobe.schema import ffprobeType, formatType, streamType, tagsType

__all__ = ["streamType", "ffprobeType", "tagsType", "formatType"]
