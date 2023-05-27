from .utils import *
from .muxing import *
from .audio import *
from .subtitle import *
from .misc import *

from . import main
from . import functions
from .main import *
from .functions import *


def entry_point():
    import sys
    from .cli import install_libraries, install_dependencies

    if sys.argv:
        if sys.argv[-1].lower() in ["libs", "libraries"]:
            install_libraries()
            sys.exit(0)
        elif sys.argv[-1].lower() in ["install", "deps", "dependencies"]:
            install_dependencies()
            sys.exit(0)

    error(
        "No arguments passed.\nYou can use [b]libs[/] or [b]libraries[/] to install/update libraries of qaac and eac3to."
        + "\nYou can use [b]install[/], [b]deps[/] or [b]dependencies[/] to install all sorts of executables."
    )
