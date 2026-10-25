import pytest

from muxtools.utils.dataclass import CLIKwargs, allow_extra, dataclass


@dataclass(config=allow_extra)
class EmptyArgs(CLIKwargs):
    pass


@dataclass(config=allow_extra)
class ConfiguredArgs(CLIKwargs):
    value: int = 1


@pytest.mark.parametrize("args_type", [EmptyArgs, ConfiguredArgs])
def test_custom_args_updates(args_type: type[EmptyArgs] | type[ConfiguredArgs]) -> None:
    args = args_type()
    args.update_custom_args(bitrate=192)
    args.update_custom_args(bitrate=256, encoder="opus")

    assert args.get_custom_args_dict() == {"bitrate": 256, "encoder": "opus"}
    assert args.get_custom_args() == ["--bitrate", "256", "--encoder", "opus"]
