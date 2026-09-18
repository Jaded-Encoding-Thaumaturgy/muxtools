import re
import sys
import shutil
import platform
from typing import Any
from pathlib import Path
from cpuinfo import get_cpu_info  # type: ignore[import-untyped]

from .types import Spec
from .sanitization import parse_spec, _installed_metadata, version_code, satisfies
from .operations import scope_path, load_catalog, resolve_name
from ..log import warn
from ...config import ProjectConfig, discover_config

__all__ = ["get_managed_executable"]

# Each tier adds to the previous tier's feature requirements.
TIER_FEATURES = {
    "baseline": {"cx16", "lahf_lm", "popcnt", "sse3", "ssse3", "sse4_1", "sse4_2"},
    "avx2": {"avx", "avx2", "bmi1", "bmi2", "f16c", "fma", "lzcnt", "movbe", "xsave"},
    "avx512": {"avx512f", "avx512bw", "avx512cd", "avx512dq", "avx512vl"},
    # cpuinfo omits MWAITX, WBNOINVD, FSGSBASE, and CLZERO on some platforms.
    # SSE4a and AVX512BF16 are deliberately disabled in the builds.
    "zn4": {
        "aes",
        "pclmul",
        "rdrand",
        "rdseed",
        "adx",
        "sha",
        "clflushopt",
        "clwb",
        "avx512ifma",
        "avx512vbmi",
        "avx512vbmi2",
        "avx512vnni",
        "avx512bitalg",
        "avx512vpopcntdq",
        "gfni",
        "vaes",
        "vpclmulqdq",
        "rdpid",
        "prfchw",
    },
}


def supports(tier: str, features: set[str]) -> bool:
    required: set[str] = set()
    for level, additions in TIER_FEATURES.items():
        required.update(additions)
        if level == tier:
            return required <= features
    raise KeyError(tier)


def cpu_state() -> set[str]:
    aliases = {
        "pni": "sse3",
        "abm": "lzcnt",
        "pclmulqdq": "pclmul",
        "rdrnd": "rdrand",
        "sha_ni": "sha",
        "3dnowprefetch": "prfchw",
    }
    try:
        cpuinfo = get_cpu_info()
        features = {aliases.get(flag, flag).replace("avx512_", "avx512") for flag in cpuinfo.get("flags", [])}  # type: ignore
        # cpuinfo merges CPUID and OS flags, so remove vector features the OS cannot use.
        if sys.platform == "win32":
            import ctypes

            enabled = ctypes.WinDLL("kernel32").GetEnabledXStateFeatures
            enabled.restype = ctypes.c_uint64
            enabled.argtypes = []
            xstate = enabled()
            avx_enabled = xstate & 6 == 6
            avx512_enabled = xstate & 0xE6 == 0xE6
        elif platform.system() == "Linux":
            flags = re.findall(r"^flags\s*:\s*(.*)$", Path("/proc/cpuinfo").read_text(), re.MULTILINE)
            enabled = set.intersection(*(set(line.split()) for line in flags)) if flags else set()
            avx_enabled = "avx" in enabled
            avx512_enabled = "avx512f" in enabled
        else:
            return set()
        # Each higher tier includes these required features, so clearing them gates that tier and above.
        if not avx_enabled:
            features.discard("avx")
        if not avx512_enabled:
            features.discard("avx512f")
        return features
    except Exception as error:
        warn(f"CPU detection unavailable; skipping optimized variants: {error}")
    return set()


def _get_fitting_variant(entry: dict[str, Any] | str, directory: Path) -> Path:
    if not isinstance(entry, (dict, str)):
        raise ValueError("Invalid executable variants")
    variants = {"baseline": entry} if isinstance(entry, str) else entry
    root = directory.resolve()
    features = cpu_state() if any(tier in variants for tier in TIER_FEATURES if tier != "baseline") else set()
    for tier in reversed(TIER_FEATURES):
        if tier != "baseline" and not supports(tier, features):
            continue
        relative = variants.get(tier)
        if not isinstance(relative, str):
            continue
        path = (directory / relative).resolve()
        if path.is_relative_to(root) and path.is_file():
            return path
    raise ValueError("No compatible executable variant is available")


def get_managed_executable(name: str, config: ProjectConfig | None = None) -> str | None:
    config = config or discover_config()
    if config is None or config.mode == "system":
        return shutil.which(name)
    root = scope_path(config)
    catalog = None
    try:
        catalog = load_catalog(offline=True)
    except ValueError:
        pass
    for raw in config.packages:
        spec = parse_spec(raw)
        package = spec.name
        if catalog:
            package = resolve_name(package, catalog)
            provided = catalog["packages"][package].get("provides", [])
        else:
            provided = [key for item in _installed_metadata(root, package) for key in item.get("binaries", {})]
        if name not in provided:
            continue
        items = _installed_metadata(root, package)
        required = version_code(Spec(package, spec.operator, spec.version), catalog["packages"].get(package, {}) if catalog else {}, root)
        valid = [item for item in items if satisfies(item["version_code"], spec.operator, required)]
        for item in sorted(valid, key=lambda value: value["version_code"], reverse=True):
            try:
                return str(_get_fitting_variant(item["binaries"][name], Path(item["_path"])))
            except (KeyError, ValueError):
                continue
        raise FileNotFoundError(f"Configured binary {name!r} is missing; run 'muxtools binaries sync'")
    return shutil.which(name)
