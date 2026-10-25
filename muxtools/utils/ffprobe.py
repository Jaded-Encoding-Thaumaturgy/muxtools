import json
import subprocess
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = ["ProbeResult", "ProbeFormat", "ProbeStream"]


class _ProbeModel(BaseModel):
    model_config = ConfigDict(frozen=True)

    raw: dict[str, Any] = Field(default_factory=dict, repr=False)

    @model_validator(mode="before")
    @classmethod
    def _keep_raw(cls, data: Any) -> Any:
        return {**data, "raw": data} if isinstance(data, dict) else data

    @classmethod
    def _optional_int(cls, value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None


class ProbeStream(_ProbeModel):
    index: int | None = None
    codec_name: str | None = None
    codec_long_name: str | None = None
    codec_type: str | None = None
    profile: str | None = None
    width: int | None = None
    height: int | None = None
    sample_aspect_ratio: str | None = None
    pix_fmt: str | None = None
    color_range: str | None = None
    color_space: str | None = None
    color_transfer: str | None = None
    color_primaries: str | None = None
    chroma_location: str | None = None
    avg_frame_rate: str | None = None
    sample_fmt: str | None = None
    sample_rate: int | None = None
    channels: int | None = None
    channel_layout: str | None = None
    bits_per_sample: int | None = None
    bits_per_raw_sample: int | None = None
    bit_rate: int | None = None
    tags: dict[str, str] = Field(default_factory=dict)
    disposition: dict[str, int] = Field(default_factory=dict)
    side_data_list: list[dict[str, Any]] = Field(default_factory=list)

    # Keep validators on the models that define their fields for static doc tools.
    @field_validator(
        "index",
        "width",
        "height",
        "sample_rate",
        "channels",
        "bits_per_sample",
        "bits_per_raw_sample",
        "bit_rate",
        mode="before",
    )
    @classmethod
    def _validate_optional_int(cls, value: Any) -> int | None:
        return cls._optional_int(value)


class ProbeFormat(_ProbeModel):
    nb_streams: int | None = None
    format_name: str | None = None
    format_long_name: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)

    @field_validator("nb_streams", mode="before")
    @classmethod
    def _validate_optional_int(cls, value: Any) -> int | None:
        return cls._optional_int(value)


class ProbeResult(_ProbeModel):
    format: ProbeFormat
    streams: list[ProbeStream] = Field(default_factory=list)
    chapters: list[dict[str, Any]] = Field(default_factory=list)


def parse_probe_json(output: str | bytes) -> ProbeResult:
    return ProbeResult.model_validate(json.loads(output))


def probe_file(path: Path, executable: str) -> ProbeResult:
    result = subprocess.run(
        [executable, "-v", "error", "-show_format", "-show_streams", "-show_chapters", "-of", "json", "-i", str(path)],
        capture_output=True,
        check=True,
        encoding="utf-8",
    )
    return parse_probe_json(result.stdout)
