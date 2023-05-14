import os
from pathlib import Path
from configparser import ConfigParser
from utils.log import error
import json


class Setup:
    """
    When you initiate this for the first time in a directory
    it will create a new config.ini. Set that up and have fun with all the other functions :)
    """

    bdmv_dir = "BDMV"
    show_name = "Nice Series"
    allow_binary_download = True
    clean_work_dirs = False
    out_dir = "premux"
    out_name = "$show$ - $ep$ (premux)"
    mkv_title_naming = r"$show$ - $ep$"
    debug = False

    episode: str = "01"
    work_dir: str = None
    webhook_url: str = None

    def __init__(self, episode: str = "01", config_file: str = "config.ini"):
        """
        :param episode:         Episode identifier(?)
        :param config_file:     Path to config file (defaults to 'config.ini' in current working dir)
        """

        if config_file:
            config = ConfigParser()
            config_name = config_file

            if not os.path.exists(config_name):
                config["SETUP"] = {
                    "bdmv_dir": self.bdmv_dir,
                    "show_name": self.show_name,
                    "allow_binary_download": self.allow_binary_download,
                    "clean_work_dirs": self.clean_work_dirs,
                    "out_dir": self.out_dir,
                    "out_name": self.out_name,
                    "mkv_title_naming": self.mkv_title_naming,
                    "debug": self.debug,
                }

                with open(config_name, "w") as config_file:
                    config.write(config_file)

                raise error(f"Template config created at {Path(config_name).resolve()}.\nPlease set it up!")

            config.read(config_name)
            settings = config["SETUP"]

            valid_bools = ["true", "1", "t", "y", "yes"]
            for key in settings:
                if hasattr(self, key) and isinstance(getattr(self, key), bool):
                    setattr(self, key, True if settings[key].lower() in valid_bools else False)
                else:
                    setattr(self, key, settings[key])

        self.episode = episode
        self.work_dir = Path(os.path.join(os.getcwd(), "_workdir", episode))
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.work_dir = str(self.work_dir)

        from utils.env import save_setup

        save_setup(self)

    def edit(self, attr: str, value: any):
        setattr(self, attr, value)

        from utils.env import save_setup

        save_setup(self)

    def toJson(self) -> str:
        return json.dumps(self.__dict__)
