import os
import shlex
import shutil
import subprocess

from .utils.log import info, warn

CONF = "([green bold]Y[/] | [red]n[/])"


def install_scoop():
    if os.name != "nt":
        info("This script does not work on anything but windows.")
        info("You should be able to install everything yourself via AUR or whatever you're using.")
    if shutil.which("scoop"):
        return

    info("This script depends on having [link=https://scoop.sh]scoop[/link] installed.")
    info(f"Do you want to install it? {CONF}")

    answer = input("")
    if answer.lower() not in ["y", "yes"]:
        info("Aborting...")
        exit(0)

    info("Setting group policy for powershell...")
    _run_powershell(["Set-ExecutionPolicy", "RemoteSigned", "-Scope", "CurrentUser"])
    info("Downloading and installing scoop for current user...")
    subprocess.run("irm get.scoop.sh | iex", shell=True, executable=shutil.which("powershell"))


def install_dependencies():
    install_scoop()
    info("Updating scoop buckets...")
    _run_powershell("scoop update", True)

    if not shutil.which("ffmpeg"):
        request_install(
            "ffmpeg",
            "This is used for ensuring compatibility for basically every encoder.",
            "anderlli0053_DEV-tools/ffmpeg-nonfree",
            ("anderlli0053_DEV-tools", "https://github.com/anderlli0053/DEV-tools"),
            "ffmpeg-nonfree",
        )

    if not shutil.which("sox"):
        request_install("SoX", "This is used & preferred for trimming lossless audio.")

    if not shutil.which("mkvmerge") or not shutil.which("mkvextract"):
        request_install(
            "Mkvtoolnix",
            "This is used for all muxing operations.\nYou might have already installed this but mkvmerge and mkvextract could not be found in path!",
            "extras/mkvtoolnix",
            ("extras", ""),
        )

    if not shutil.which("opusenc"):
        request_install("opus-tools", "This is used for encoding audio to opus via opusenc.")

    if not shutil.which("flac"):
        request_install("FLAC", "This is used for encoding audio to flac via the official reference encoder.")

    if not shutil.which("qaac"):
        if not request_install("qaac", "This is used for encoding audio to aac."):
            warn("qAAC requires external libraries from iTunes because apple is funny.\nYou can automatically install these with [b u]libs[/].")

    if not shutil.which("eac3to"):
        if not request_install(
            "eac3to", "This is used for audio extraction/processing.\nMostly useless due to the ffmpeg implementation in this package."
        ):
            warn(
                "eac3to has some stupid sounds included that play when processing finishes."
                + "\nIt also has a bunch of outdated libraries included."
                + "\nYou can automatically solve these issues with [b u]libs[/]."
            )


def request_install(
    name: str, description: str, scoop_package: str | None = None, scoop_bucket: tuple[str] | None = None, exact_name: str | None = None
) -> int:
    info(f"Do you want to install {name}? {CONF}\n{description}")
    answer = input("")
    if answer.lower() in ["y", "yes"]:
        if scoop_bucket:
            info(f"Adding scoop bucket '{scoop_bucket[0]}'...")
            _run_powershell(f"scoop bucket add {scoop_bucket[0]} {scoop_bucket[1]}")
            _run_powershell("scoop update", True)
        info(f"Installing {exact_name if exact_name else name} via scoop...")
        return _run_powershell(f"scoop install {scoop_package if scoop_package else name.lower()} -u")
    return -1


def _run_powershell(args: str | list[str], quiet: bool = False) -> int:
    if isinstance(args, str):
        args = shlex.split(args)
    pwsh = [shutil.which("powershell")]
    pwsh.extend(args)
    if quiet:
        p = subprocess.Popen(pwsh, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        p = subprocess.Popen(pwsh)
    p.communicate()
    return p.returncode
