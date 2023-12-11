import os
import re
import wget
import shlex
import shutil
import subprocess
from pathlib import Path

from .utils.log import info, warn
from .utils.download import unpack_all
from .utils.env import get_temp_workdir
from .utils.files import clean_temp_files

CONF = "([green bold]Y[/] | [red]n[/])"

LINKS = [
    "https://www.rarewares.org/files/lossless/flac_dll-1.4.3-x86.zip",
    "https://github.com/xiph/flac/releases/download/1.4.3/flac-1.4.3-win.zip",
    "https://github.com/dbry/WavPack/releases/download/5.6.0/wavpack-5.6.0-dll.zip",
    "https://github.com/libsndfile/libsndfile/releases/download/1.2.0/libsndfile-1.2.0-win64.zip",
    "https://files.catbox.moe/bkj665.7z",  # Sourced from https://github.com/AnimMouse/QTFiles/ but the file there can't be extracted by py7zr
]


def install_libraries():
    if os.name != "nt":
        info("This script does not work on anything but windows.")
        exit()

    temp = get_temp_workdir()
    dir = get_exe_folder("eac3to")
    if dir:
        info(f"Do you want to install updated libraries for eac3to? {CONF}")
        if input("").lower() in ["y", "yes"]:
            info("Downloading libFLAC (32 bit for eac3to)...")
            wget.download(LINKS[0], str(temp), None)
            unpack_all(temp)
            find_and_rename(temp, r"libFLAC_dynamic\.dll", Path(dir, "libFLAC.dll"))
        clean_temp_files()
        info(f"Do you want to delete the awful eac3to sounds? {CONF}")
        if input("").lower() in ["y", "yes"]:
            for f in dir.rglob("*.wav"):
                f.unlink(True)

    temp = get_temp_workdir()
    dir = get_exe_folder("qaac")
    if dir:
        info(f"Do you want to install updated/new libraries for qaac? {CONF}")
        if input("").lower() in ["y", "yes"]:
            info("Downloading libFLAC...")
            wget.download(LINKS[1], str(temp), None)

            info("Downloading wavpack...")
            wget.download(LINKS[2], str(temp), None)

            info("Downloading libsndfile...")
            wget.download(LINKS[3], str(temp), None)
            unpack_all(temp)

            find_and_rename(temp, r"libFLAC\.dll", Path(dir, "libFLAC.dll"), True)
            find_and_rename(temp, r"wavpackdll\.dll", Path(dir, "wavpackdll.dll"), True)
            find_and_rename(temp, r"sndfile\.dll", Path(dir, "sndfile.dll"))
            clean_temp_files()
            temp = get_temp_workdir()

            info("Downloading iTunes libraries...")
            wget.download(LINKS[4], str(temp), None)
            unpack_all(temp)
            find_and_rename(temp, r".*\.dll", dir)

    clean_temp_files()


def find_and_rename(dir: Path, pattern: str, renameto: Path, x64_parent_dir: bool = False):
    regex = re.compile(pattern, re.IGNORECASE)
    if not renameto.is_dir() and renameto.exists():
        renameto.unlink()
    for f in dir.rglob("*"):
        if x64_parent_dir:
            if "64" not in f.parent.name:
                continue
        if regex.match(f.name):
            if renameto.is_dir():
                shutil.move(f, Path(renameto, f.name))
            else:
                shutil.move(f, renameto)
                break


def install_scoop():
    if os.name != "nt":
        info("This script does not work on anything but windows.")
        info("You should be able to install everything yourself via AUR or whatever you're using.")
        exit()
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
    os.environ["PATH"] += os.pathsep + str(Path(str(os.environ["USERPROFILE"]), "scoop", "shims").resolve())


def install_dependencies():
    install_scoop()
    info("Updating scoop buckets...")
    _run_powershell("scoop update", True)

    if not shutil.which("git"):
        request_install("git", "Needed for a lot of things. Just install it.")

    if not shutil.which("ffmpeg"):
        request_install(
            "ffmpeg",
            "This is used for ensuring compatibility for basically every encoder.",
            "versions/ffmpeg-gyan-nightly",
            ("versions", ""),
            "ffmpeg-gyan-nightly",
        )
    if not shutil.which("fdkaac"):
        request_install(
            "fdkaac",
            "The second best AAC encoder. Not really necessary tbf.",
            "vodes/fdkaac",
            ("vodes", "https://github.com/Vodes/Bucket"),
            "fdkaac",
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
        request_install(
            "opus-tools",
            "This is used for encoding audio to opus via opusenc.",
            "vodes/opus-tools-rarewares",
            ("vodes", "https://github.com/Vodes/Bucket"),
        )

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

    print("\n\n")
    install_libraries()


def request_install(
    name: str, description: str, scoop_package: str | None = None, scoop_bucket: tuple[str, str] | None = None, exact_name: str | None = None
) -> int:
    info(f"Do you want to install {name}? {CONF}\n{description}")
    if input("").lower() in ["y", "yes"]:
        if scoop_bucket:
            info(f"Adding scoop bucket '{scoop_bucket[0]}'...")
            _run_powershell(f"scoop bucket add {scoop_bucket[0]} {scoop_bucket[1]}")
            _run_powershell("scoop update", True)
        info(f"Installing {exact_name if exact_name else name} via scoop...")
        return _run_powershell(f"scoop install {scoop_package if scoop_package else name.lower()} -u -a 64bit")
    return -1


def get_exe_folder(name: str) -> Path:
    exe_path = shutil.which(name)
    if exe_path:
        exe_path = Path(exe_path)
        # if this was installed with scoop
        if exe_path.parent.name == "shims":
            return Path(exe_path.parent.parent, "apps", name, "current")
        else:
            return exe_path.parent
    return exe_path


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
    print("")
    return p.returncode
