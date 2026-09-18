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
    from rich.console import Console
    from rich.text import Text

    from .cli import app

    try:
        app()
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except ValueError as exc:
        message = Text("✗ ", style="bold red")
        message.append(str(exc))
        Console(stderr=True).print(message)
        raise SystemExit(1) from None
