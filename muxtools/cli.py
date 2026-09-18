"""The muxtools command-line interface."""

from __future__ import annotations

import sys
import shutil
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, Literal

from cyclopts import App, Parameter
from rich.text import Text

from .utils import binaries as manager
from .config import BinaryMode, ProjectConfig, discover_config, init_config, migrate_config
from .utils.convert import get_timemeta_from_video
from .utils.files import ensure_path_exists
from .utils.probe import ParsedFile

app = App(name="muxtools")
binaries = App(name=["binaries", "bin"])
app.command(binaries)


def _choose(message: str, choices: list[str]) -> str:
    if not sys.stdin.isatty():
        raise ValueError(f"{message}: provide a choice as an argument")
    import questionary

    try:
        answer = questionary.select(message, choices=choices).ask()
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    if answer is None:
        raise SystemExit(130)
    return answer


def _choose_many(message: str, choices: list[str]) -> list[str]:
    if not sys.stdin.isatty():
        raise ValueError(f"{message}: provide choices as arguments")
    import questionary
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.keys import Keys
    from questionary.prompts.common import InquirerControl

    prompt = questionary.checkbox(message, choices=choices, instruction="Enter: highlighted or checked · Space: toggle selections")
    control = next(window.content for window in prompt.application.layout.find_all_windows() if isinstance(window.content, InquirerControl))
    bindings = prompt.application.key_bindings
    assert isinstance(bindings, KeyBindings)
    bindings.remove(Keys.ControlM)

    @bindings.add(Keys.ControlM, eager=True)
    def submit(event: Any) -> None:
        selected = control.get_selected_values() or [control.get_pointed_at()]
        control.is_answered = True
        event.app.exit(result=[choice.value for choice in selected])

    try:
        answer = prompt.ask()
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    if answer is None:
        raise SystemExit(130)
    return answer


def _specs(values: tuple[str, ...], catalog: dict[str, Any], offline: bool = False) -> list[str]:
    if values:
        return list(values)
    latest = "latest installed version" if offline else "latest version"
    selected = _choose_many(f"Select packages (multiple: {latest} of each)", sorted(catalog["packages"]))
    if len(selected) != 1:
        return selected
    name = selected[0]
    versions = catalog["packages"][name]["versions"]
    if not versions:
        raise ValueError(f"No catalog versions are available for {name}")
    version = _choose("Select a version", sorted(versions, key=lambda key: versions[key]["version_code"], reverse=True))
    return [f"{name}=={version}"]


def _result(
    label: str,
    value: str | Path | None = None,
    detail: str | Text | None = None,
    *,
    kind: Literal["success", "existing", "system"] = "success",
) -> None:
    marker, marker_style = {"success": ("✓", "bold green"), "existing": ("•", "bold cyan"), "system": ("✓", "bold cyan")}[kind]
    line = Text(f"{marker} ", style=marker_style)
    line.append(label, style="bold")
    if value is not None:
        line.append(f" {value}", style="cyan")
    if detail:
        line.append(" · ", style="dim")
        if isinstance(detail, Text):
            line.append(detail)
        else:
            line.append(detail, style="dim" if kind == "success" else "cyan" if kind == "system" else None)
    app.console.print(line)


@app.command
def init(
    *,
    standalone: Annotated[bool, Parameter(negative=False)] = False,
    pyproject: Annotated[bool, Parameter(negative=False)] = False,
    local: Annotated[bool, Parameter(name=["--local", "-l"], negative=False, help="Use binaries installed in this project.")] = False,
    global_: Annotated[bool, Parameter(name=["--global", "-g"], negative=False, help="Use binaries installed for this user.")] = False,
    system: Annotated[bool, Parameter(name=["--system", "-s"], negative=False, help="Use executables on PATH.")] = False,
) -> None:
    """Initialize project configuration. Prompts for a binary mode in a terminal; defaults to local in scripts."""
    if standalone and pyproject:
        raise ValueError("Choose only one of --standalone and --pyproject")
    if sum((local, global_, system)) > 1:
        raise ValueError("Choose only one of --local, --global, and --system")
    name = "muxtools.toml" if standalone else "pyproject.toml" if pyproject else _choose("Configuration file", ["pyproject.toml", "muxtools.toml"])
    if local or global_ or system:
        mode: BinaryMode = "local" if local else "global" if global_ else "system"
    elif sys.stdin.isatty():
        modes: dict[str, BinaryMode] = {"Local (project)": "local", "Global (user)": "global", "System (PATH)": "system"}
        mode = modes[_choose("Binary mode", list(modes))]
    else:
        mode = "local"
    config = init_config(Path(name), mode)
    _result("Configuration ready:", config.path, f"{config.mode} binaries")


@app.command(name="migrate-config")
def migrate_config_command(source: Path = Path("config.ini"), *, destination: Path) -> None:
    """Copy legacy INI settings into a selected TOML file."""
    _result("Migrated configuration:", migrate_config(source, destination).path)


@app.command(name=["video-meta", "vm"])
def video_meta(input: Path, output: Path | None = None) -> None:
    """Generate VideoMeta JSON from a video."""
    path = ensure_path_exists(input, None)
    parsed = ParsedFile.from_file(path, None, False)
    if not parsed.is_video_file:
        raise ValueError(f"{path.name!r} is not a video file")
    destination = output or Path.cwd() / f"{path.stem}_meta.json"
    get_timemeta_from_video(path, 0, destination, parsed, None)
    _result("VideoMeta written:", destination)


@binaries.command
def add(*specs: str, offline: bool = False) -> None:
    """Declare and install packages in the current project."""
    config = discover_config()
    if config is None:
        raise ValueError("No project configuration found; run 'muxtools init'")
    catalog = manager.load_catalog(offline)
    selected = _specs(specs, catalog, offline)
    if not selected:
        app.console.print("[dim]No packages selected.[/dim]")
        return
    _, versions = manager.add(config, selected, offline, catalog)
    for name, version in versions.items():
        if config.mode == "system":
            _result(name, f"{version} (catalog)", "declared; system version not checked", kind="system")
        else:
            location = "locally" if config.mode == "local" else "globally"
            _result(
                name,
                version,
                f"{'already installed' if offline else 'installed'} {location}, added to project",
                kind="existing" if offline else "success",
            )


@binaries.command
def install(
    *specs: str,
    local: Annotated[bool, Parameter(name=["--local", "-l"])] = False,
    global_: Annotated[bool, Parameter(name=["--global", "-g"])] = False,
    offline: bool = False,
) -> None:
    """Install packages without modifying project declarations."""
    if local and global_:
        raise ValueError("Choose only one of --local and --global")
    config = discover_config()
    scope = "local" if local else "global" if global_ else None
    mode = scope or (config.mode if config else "global")
    root = manager.scope_path(config, scope)
    catalog = manager.load_catalog(offline)
    selected = _specs(specs, catalog, offline)
    if not selected:
        app.console.print("[dim]No packages selected.[/dim]")
        return
    for raw in selected:
        spec = manager.parse_spec(raw)
        if offline:
            name = manager.resolve_name(spec.name, catalog)
            canonical = manager.Spec(name, spec.operator, spec.version)
            matches = manager.usable_installed(canonical, catalog["packages"][name], root)
            if not matches:
                raise ValueError(f"{name} is missing and cannot be installed offline")
            item = max(matches, key=lambda value: value["version_code"])
        else:
            item = manager.install(spec, catalog, root)
        location = "locally" if mode == "local" else "globally"
        _result(
            item["name"], item["version"], f"{'already installed' if offline else 'installed'} {location}", kind="existing" if offline else "success"
        )


@binaries.command
def sync(*, offline: bool = False) -> None:
    """Ensure project binary declarations are available."""
    config = discover_config()
    if config is None:
        raise ValueError("No project configuration found")
    if not config.packages:
        app.console.print("[dim]No packages declared.[/dim]")
        return
    results = manager.sync(config, offline)
    location = "locally" if config.mode == "local" else "globally"
    for result in results:
        if result.state == "installed":
            _result(result.name, result.version, f"installed {location}")
        elif result.state == "existing":
            _result(result.name, result.version, f"already installed {location}", kind="existing")
        else:
            detail = Text("available on PATH", style="cyan")
            if result.version_unchecked:
                detail.append(" (version not checked)", style="yellow")
            _result(result.name, detail=detail, kind="system")


@binaries.command(name="list")
def list_binaries(*, global_: Annotated[bool, Parameter(name=["--global", "-g"])] = False) -> None:
    """Show installed versions and the version selected by this project."""
    config = discover_config()
    if config is None and not global_:
        app.console.print("[yellow]No project configuration found.[/yellow]")
        return
    try:
        catalog = manager.load_catalog(offline=True)
    except ValueError:
        catalog = None
    if config and config.mode == "system" and not global_:
        app.console.print(Text("Project binaries (system)", style="bold cyan"))
        for raw in config.packages:
            spec = manager.parse_spec(raw)
            package = catalog["packages"].get(spec.name) if catalog else None
            provided = package.get("provides", []) if package else [spec.name]
            missing = [binary for binary in provided if not shutil.which(binary)]
            line = Text(f"{spec.name}: ", style="bold")
            line.append("missing " + ", ".join(missing) if missing else "available on PATH", style="yellow" if missing else "green")
            if spec.operator:
                line.append(" (version not checked)", style="dim")
            app.console.print(line)
        if not config.packages:
            app.console.print("[dim]No packages declared.[/dim]")
        return

    if global_:
        scope = "global"
    else:
        assert config is not None
        scope = config.mode
    root = manager.scope_path(config, scope)
    items = manager.installed(root)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        grouped[item["name"]].append(item)
    selected: dict[str, str] = {}
    problems: dict[str, str] = {}
    if config and config.mode == scope:
        selected, problems = _project_versions(config, catalog, root, items)
    app.console.print(Text("Global binaries" if global_ else f"Project binaries ({scope})", style="bold cyan"))
    names = sorted(grouped.keys() | problems.keys() | selected.keys())
    if not names:
        app.console.print("[dim]No installed binaries.[/dim]")
        return
    for name in names:
        line = Text(f"{name}: ", style="bold")
        versions = sorted(grouped.get(name, []), key=lambda item: item["version_code"], reverse=True)
        for index, item in enumerate(versions):
            if index:
                line.append(", ")
            active = selected.get(name) == item["version"]
            line.append(item["version"], style="green" if active else None)
            if active:
                line.append("*", style="bold green")
        if name in problems:
            if versions:
                line.append(" ")
            line.append(f"({problems[name]})", style="yellow")
        app.console.print(line)
    if selected:
        app.console.print("[dim]* selected by the current project[/dim]")


def _project_versions(
    config: ProjectConfig, catalog: dict[str, Any] | None, root: Path, items: list[dict[str, Any]]
) -> tuple[dict[str, str], dict[str, str]]:
    selected = {}
    problems = {}
    for raw in config.packages:
        spec = manager.parse_spec(raw)
        try:
            name = manager.resolve_name(spec.name, catalog) if catalog else spec.name
            package = catalog["packages"][name] if catalog else {}
            matches = manager.usable_installed(manager.Spec(name, spec.operator, spec.version), package, root, items)
        except ValueError:
            problems[spec.name] = "unknown package or constraint version"
            continue
        if matches:
            selected[name] = max(matches, key=lambda item: item["version_code"])["version"]
        else:
            problems[name] = "needs sync"
    return selected, problems


@binaries.command
def remove(*names: str) -> None:
    """Remove package declarations from project configuration."""
    config = discover_config()
    if config is None:
        raise ValueError("No project configuration found")
    if not names and not config.packages:
        app.console.print("[dim]No packages declared.[/dim]")
        return
    selected = (
        list(names)
        if names
        else _choose_many("Select declarations to remove", list(dict.fromkeys(manager.parse_spec(raw).name for raw in config.packages)))
    )
    if not selected:
        app.console.print("[dim]No packages selected.[/dim]")
        return
    updated = manager.remove(config, selected)
    removed = [manager.parse_spec(raw) for raw in config.packages if raw not in updated.packages]
    for spec in removed:
        version = ("" if spec.operator == "==" else spec.operator) + spec.version if spec.operator and spec.version else None
        _result(spec.name, version, "removed from project")
    if not removed:
        app.console.print("[yellow]No matching project declarations.[/yellow]")


@binaries.default
def binaries_menu() -> None:
    """Choose a binary management action."""
    if not sys.stdin.isatty():
        app.help_print("binaries")
        return
    config = discover_config()
    actions: dict[str, Callable[[], None]]
    if config is None:
        actions = {
            "Initialize project": init,
            "Install globally": lambda: install(global_=True),
            "List global binaries": lambda: list_binaries(global_=True),
        }
    else:

        def install_selected() -> None:
            if config.mode == "system":
                scope = _choose("Install scope", ["global", "local"])
                install(global_=scope == "global", local=scope == "local")
            else:
                install()

        actions = {
            "List project binaries": list_binaries,
            "List global binaries": lambda: list_binaries(global_=True),
            "Add package": add,
            "Install package": install_selected,
            "Sync project": sync,
        }
        if config.packages:
            actions["Remove declaration"] = remove
    actions[_choose("Choose a binary action", list(actions))]()
