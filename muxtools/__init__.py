from .utils import *
from .muxing import *
from .audio import *
from .subtitle import *
from .misc import *
from .helpers import *

from . import main
from . import functions
from .main import *
from .functions import *

__version__: str
__version_tuple__: tuple[int | str, ...]

try:
    from ._version import __version__, __version_tuple__
except ImportError:
    __version__ = "0.0.0+unknown"
    __version_tuple__ = (0, 0, 0, "+unknown")


def entry_point():
    import sys
    from .cli import install_libraries, install_dependencies, generate_videometa

    if sys.argv:
        if sys.argv[-1].lower() in ["libs", "libraries"]:
            install_libraries()
            sys.exit(0)
        elif sys.argv[-1].lower() in ["install", "deps", "dependencies"]:
            install_dependencies()
            sys.exit(0)
        else:
            if len(sys.argv) > 1:
                if sys.argv[1].lower() in ["gen-vm", "generate-videometa"]:
                    file_in = None if len(sys.argv) < 3 else sys.argv[2]
                    file_out = None if len(sys.argv) < 4 else sys.argv[3]
                    generate_videometa(file_in, file_out)
                    sys.exit(0)

    error(
        "No arguments passed.\nYou can use [b]libs[/] or [b]libraries[/] to install/update libraries of qaac and eac3to."
        + "\nYou can use [b]install[/], [b]deps[/] or [b]dependencies[/] to install all sorts of executables.\n\n"
        + "You can also use [b]generate-videometa[/] or [b]gen-vm[/] to generate a VideoMeta file for a video."
    )
