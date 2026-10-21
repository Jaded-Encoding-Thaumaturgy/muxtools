import os
import re
import sys
import shutil
import platform
from typing import Any
from pathlib import Path
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from cpuinfo import get_cpu_info  # type: ignore[import-untyped]

from .types import Spec
from .sanitization import parse_spec, _installed_metadata, resolve_installed_name
from .operations import scope_path, load_catalog, matching_installed
from ..log import warn
from ...config import ProjectConfig, discover_config, resolve_binary_config

__all__ = ["get_managed_executable", "use_binary_package"]

_package_selections: ContextVar[dict[str, str]] = ContextVar("binary_package_selections", default={})

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


def _cached_catalog() -> dict[str, Any] | None:
    try:
        return load_catalog(offline=True)
    except (ValueError, OSError):
        return None


def _validate_package(package: str) -> None:
    if parse_spec(package).operator is not None:
        raise ValueError("Package selection requires a canonical package name without a version constraint")


def _provided(package: str, items: list[dict[str, Any]], catalog: dict[str, Any] | None) -> set[str]:
    names = set(catalog["packages"].get(package, {}).get("provides", [])) if catalog else set()
    names.update(name for item in items if item["name"] == package for name in item.get("binaries", {}))
    return names


def _package_executable(name: str, spec: Spec, root: Path, items: list[dict[str, Any]], catalog: dict[str, Any] | None) -> str:
    package = catalog["packages"].get(spec.name, {}) if catalog else {}
    valid = matching_installed(spec, package, root, items)
    for item in sorted(valid, key=lambda value: value["version_code"], reverse=True):
        try:
            return str(_get_fitting_variant(item["binaries"][name], Path(item["_path"])))
        except (KeyError, ValueError):
            continue
    raise FileNotFoundError(
        f"Binary {name!r} from package {str(spec)!r} is missing or incompatible; "
        "run 'muxtools binaries sync' for declared packages or 'muxtools binaries install'"
    )


@contextmanager
def use_binary_package(package: str) -> Generator[None, None, None]:
    """Select an installed provider for its executables within this block.

    Honors configured version constraints and leaves unrelated executable lookups
    unchanged. Nested selections are restored on exit. Without configuration,
    packages are read from global storage; system mode does not support selection.
    """
    _validate_package(package)
    config = resolve_binary_config(discover_config())
    root = scope_path(config)
    items = _installed_metadata(root)
    if not any(item["name"] == package for item in items):
        raise FileNotFoundError(f"Package {package!r} is not installed; run 'muxtools binaries install {package}'")
    names = _provided(package, items, _cached_catalog())
    token = _package_selections.set(_package_selections.get() | dict.fromkeys(names, package))
    try:
        yield
    finally:
        _package_selections.reset(token)


def get_managed_executable(name: str, config: ProjectConfig | None = None, *, package: str | None = None) -> str | None:
    """Resolve an executable, optionally selecting a canonical installed package.

    Selection honors configured constraints and never falls back to another
    provider. Custom ``vof_exe_*`` paths take precedence over package selection.
    Strict binary configuration disables PATH fallback for undeclared executables.
    """
    return _resolve_executable(name, config, package=package)


def _path_fallback(name: str, strict: bool) -> str | None:
    if strict:
        raise FileNotFoundError(
            f"No managed package is configured to provide {name!r}; strict mode disables PATH fallback. "
            f"Run 'muxtools binaries add {name}' in a project or select an installed package explicitly."
        )
    return shutil.which(name)


def _resolve_executable(
    name: str, config: ProjectConfig | None = None, *, package: str | None = None, default_global: bool = False, strict: bool = False
) -> str | None:
    custom = os.environ.get(f"vof_exe_{name.lower()}")
    if custom:
        path = Path(custom)
        if path.exists():
            return str(path.resolve())
        raise FileNotFoundError(f"Custom executable for {name} not found: {custom}")
    effective_config = resolve_binary_config(config if config is not None else discover_config())
    strict = strict or (effective_config.strict if effective_config else False)
    if strict and effective_config is not None and effective_config.mode == "system":
        raise ValueError('Strict binary resolution cannot use prefer = "system"; choose "local" or "global"')
    selected = package if package is not None else _package_selections.get().get(name)
    if selected is not None:
        _validate_package(selected)
    else:
        if effective_config is None and not default_global:
            return _path_fallback(name, strict)
        if effective_config is not None and effective_config.mode == "system":
            return _path_fallback(name, strict)
    root = scope_path(effective_config)
    catalog = _cached_catalog()
    installed_items = _installed_metadata(root)
    spec = Spec(selected) if selected is not None else None
    if selected is None and effective_config is None:
        providers = {item["name"] for item in installed_items if name in item.get("binaries", {})}
        if not providers:
            raise FileNotFoundError(f"No globally installed binary {name!r}; run 'muxtools binaries install -g {name}'")
        spec = Spec(min(providers, key=lambda value: (len(value), value)))
    for raw in effective_config.packages if effective_config else ():
        declared = parse_spec(raw)
        provider = resolve_installed_name(declared.name, installed_items, catalog)
        if selected is not None:
            if provider != selected:
                continue
        elif name not in _provided(provider, installed_items, catalog):
            continue
        spec = Spec(provider, declared.operator, declared.version)
        break
    return _package_executable(name, spec, root, installed_items, catalog) if spec is not None else _path_fallback(name, strict)
