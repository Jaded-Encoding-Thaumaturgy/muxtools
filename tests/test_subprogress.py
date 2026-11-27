import subprocess
import sys

from muxtools.utils.subprogress import ProgressBarConfig, run_cmd_pb


def test_run_cmd_pb_upstream_failure_propagates_and_prints_stderr(capsys) -> None:
    upstream = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import sys; sys.stdout.buffer.write(b'chunk'); sys.stdout.buffer.flush(); "
            "sys.stderr.buffer.write(b'ffmpeg: ' + b'x' * (128 * 1024) + b'\\r\\nupstream fatal error\\r\\n'); sys.exit(2)",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
    )
    downstream = [sys.executable, "-c", "import sys; sys.stdin.buffer.read(); sys.exit(0)"]

    code = run_cmd_pb(downstream, silent=True, pbc=ProgressBarConfig("Piping..."), stdin=upstream)
    out = capsys.readouterr().out

    assert code == 2
    assert upstream.returncode == 2
    assert "----------------------" in out.splitlines()
    assert "upstream fatal error" in out
    assert "\r" not in out


def test_run_cmd_pb_downstream_failure_terminates_upstream(capsys) -> None:
    upstream = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
    )
    downstream = [sys.executable, "-c", "import sys; print('encoder invalid option', file=sys.stderr); sys.exit(3)"]

    code = run_cmd_pb(downstream, silent=True, pbc=ProgressBarConfig("Piping..."), stdin=upstream)
    out = capsys.readouterr().out

    assert code == 3
    assert upstream.poll() is not None
    assert "encoder invalid option" in out
