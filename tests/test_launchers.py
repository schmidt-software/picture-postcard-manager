"""Static and runtime checks for the run.cmd / run.sh Docker launchers (#67).

Static checks parse both launchers without Docker: exact filenames, Git file
modes (run.sh must stay executable, mode 100755), line-ending policy
(LF for the POSIX script, CRLF for the batch file, pinned in .gitattributes),
quoting, volume handling, health-endpoint readiness and the absence of
destructive Docker flags.

Runtime checks execute run.sh on POSIX hosts against stub docker / curl /
browser commands placed first on PATH, asserting the fresh start, the safe
rerun paths (running and stopped container), the Docker-missing error and the
bounded health timeout. No real Docker daemon, network access or data is used.
"""

import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_SH = ROOT / "run.sh"
RUN_CMD = ROOT / "run.cmd"

CONTAINER = "picture-postcard-manager"
VOLUME = "postcard-data"
IMAGE_PREFIX = "ghcr.io/schmidt-software/picture-postcard-manager:"
HEALTH_PATH = "/api/health"


def git_index_modes():
    """Return {path: mode} for the launchers from the Git index, or None."""
    try:
        output = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "-s", "--",
             "run.sh", "run.cmd", ".gitattributes"],
            capture_output=True, text=True, check=True, timeout=30,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    modes = {}
    for line in output.splitlines():
        mode, _blob, _stage_and_path = line.split(" ", 2)
        modes[line.split("\t", 1)[1]] = mode
    return modes or None


class LauncherFilesTest(unittest.TestCase):
    """Exact filenames, Git modes and line-ending policy."""

    def test_exact_filenames_exist(self):
        self.assertTrue(RUN_SH.is_file(), "run.sh is missing")
        self.assertTrue(RUN_CMD.is_file(), "run.cmd is missing")

    def test_git_modes(self):
        modes = git_index_modes()
        if modes is None:
            self.skipTest("not a Git checkout (archive export?)")
        self.assertEqual(modes.get("run.sh"), "100755",
                         "run.sh must be committed executable (Git mode 100755)")
        self.assertEqual(modes.get("run.cmd"), "100644",
                         "run.cmd must be a plain file (Git mode 100644)")
        self.assertIn(".gitattributes", modes,
                      ".gitattributes must be committed to pin line endings")

    def test_run_sh_is_executable_on_disk(self):
        if os.name != "posix":
            self.skipTest("POSIX permission bits")
        mode = RUN_SH.stat().st_mode
        self.assertTrue(mode & stat.S_IXUSR, "run.sh lost its executable bit")

    def test_gitattributes_pin_launcher_line_endings(self):
        attributes = (ROOT / ".gitattributes").read_text(encoding="ascii")
        self.assertRegex(attributes, r"(?m)^run\.sh\s+text\s+eol=lf\s*$")
        self.assertRegex(attributes, r"(?m)^run\.cmd\s+text\s+eol=crlf\s*$")

    def test_run_sh_uses_lf_only(self):
        data = RUN_SH.read_bytes()
        self.assertNotIn(b"\r", data, "run.sh must use LF line endings only")
        self.assertTrue(data.startswith(b"#!/bin/sh\n"))
        data.decode("ascii")  # No non-ASCII content sneaks into the launcher.

    def test_run_cmd_uses_crlf_throughout(self):
        data = RUN_CMD.read_bytes()
        self.assertTrue(data.startswith(b"@echo off\r\n"))
        # Every line break must be CRLF: cmd.exe mis-parses labels and
        # multi-line blocks in LF-only batch files.
        self.assertNotRegex(data, rb"(?<!\r)\n")
        data.decode("ascii")  # cmd.exe code pages mangle non-ASCII bytes.


class LauncherContentTest(unittest.TestCase):
    """Shared content rules for both launchers."""

    @classmethod
    def setUpClass(cls):
        cls.sh = RUN_SH.read_text(encoding="ascii")
        cls.cmd = RUN_CMD.read_text(encoding="ascii")

    def test_documented_image_container_and_volume(self):
        for text in (self.sh, self.cmd):
            self.assertIn(IMAGE_PREFIX, text)
            self.assertIn(CONTAINER, text)
            self.assertIn(VOLUME, text)
            self.assertIn(HEALTH_PATH, text)
            self.assertIn("127.0.0.1", text)

    def test_no_destructive_docker_commands_or_flags(self):
        for name, text in (("run.sh", self.sh), ("run.cmd", self.cmd)):
            with self.subTest(name):
                code = "\n".join(
                    line for line in text.splitlines()
                    if not line.lstrip().startswith(("#", "rem ", "rem\t"))
                )
                self.assertNotIn("docker rm", code)
                self.assertNotIn("volume rm", code)
                self.assertNotIn("compose down", code)
                self.assertNotIn("--rm", code)
                self.assertNotIn("--force", code)
                self.assertNotIn("prune", code)
                self.assertNotIn("rm -", code)
                self.assertNotIn("del ", code.lower())

    def test_docker_availability_is_checked_before_use(self):
        self.assertLess(self.sh.index("command -v docker"),
                        self.sh.index("docker volume create"))
        self.assertIn("docker info", self.sh)
        self.assertLess(self.cmd.index("where docker"),
                        self.cmd.index("docker volume create"))
        self.assertIn("docker info", self.cmd)

    def test_rerun_reuses_existing_container(self):
        for text in (self.sh, self.cmd):
            self.assertIn("container inspect", text)
            self.assertIn("{{.State.Running}}", text)
            self.assertIn("docker start", text)
            # Exactly one container-creating docker run invocation in code
            # (comments may mention the documented command).
            code = "\n".join(
                line for line in text.splitlines()
                if not line.lstrip().lower().startswith(("#", "rem"))
            )
            self.assertEqual(len(re.findall(r"\bdocker run -d\b", code)), 1)

    def test_bounded_timeout_is_configurable(self):
        for text in (self.sh, self.cmd):
            self.assertIn("PPM_WAIT_SECONDS", text)
            self.assertIn("90", text)

    def test_browser_opens_only_after_health_success(self):
        # run.sh: the open/xdg-open block follows the readiness loop.
        self.assertLess(self.sh.index("until probe_health"),
                        self.sh.index('open "$URL"'))
        self.assertIn("xdg-open", self.sh)
        # run.cmd: "start" of the URL lives after the :ready label, which is
        # reached only when the curl health probe succeeded.
        self.assertLess(self.cmd.index(":health_loop"), self.cmd.index(":ready"))
        self.assertLess(self.cmd.index(":ready"), self.cmd.index('start "" "%URL%"'))
        self.assertIn("curl.exe", self.cmd)

    def test_run_sh_quotes_every_expansion(self):
        # All docker arguments built from variables must be double-quoted so
        # custom ports and names with unusual characters cannot split words.
        self.assertIn('-p "127.0.0.1:$PORT:8000"', self.sh)
        self.assertIn('-v "$VOLUME:/data"', self.sh)
        self.assertIn('"$IMAGE"', self.sh)
        self.assertIn('docker start "$CONTAINER"', self.sh)
        self.assertIn('docker volume create "$VOLUME"', self.sh)
        self.assertNotRegex(
            self.sh,
            r"docker (run|start|volume create)[^\n]*(?<![\"\w])\$[A-Z_]+",
            "unquoted variable in a docker invocation",
        )

    def test_run_sh_is_strict_posix_sh(self):
        self.assertIn("set -eu", self.sh)
        self.assertNotIn("[[", self.sh)  # Bashism; the shebang is /bin/sh.

    def test_run_cmd_quotes_docker_arguments(self):
        self.assertIn('-p "127.0.0.1:%PPM_PORT%:8000"', self.cmd)
        self.assertIn('-v "%VOLUME%:/data"', self.cmd)
        self.assertIn('"%IMAGE%"', self.cmd)
        self.assertIn('docker start "%CONTAINER%"', self.cmd)

    def test_run_sh_syntax_checks(self):
        if os.name != "posix":
            self.skipTest("needs a POSIX sh")
        subprocess.run(["sh", "-n", str(RUN_SH)], check=True, timeout=30)


STUB_DOCKER = textwrap.dedent("""\
    #!/bin/sh
    # Test stub for the Docker CLI: records calls, simulates container state.
    echo "docker $*" >> "$STUB_LOG"
    case "$1 $2" in
    "info ") exit "${STUB_INFO_EXIT:-0}" ;;
    "volume create") exit 0 ;;
    "container inspect")
        state=$(cat "$STUB_STATE")
        [ "$state" = missing ] && exit 1
        echo "$state"
        exit 0 ;;
    "run -d") echo true > "$STUB_STATE"; echo cid; exit 0 ;;
    "start "*|"start") echo true > "$STUB_STATE"; exit 0 ;;
    esac
    case "$1" in
    info) exit "${STUB_INFO_EXIT:-0}" ;;
    start) echo true > "$STUB_STATE"; exit 0 ;;
    run) echo true > "$STUB_STATE"; echo cid; exit 0 ;;
    esac
    exit 0
    """)

STUB_CURL = textwrap.dedent("""\
    #!/bin/sh
    # Health probe stub: healthy only when the container stub is "running",
    # and only after a configurable number of failing polls.
    echo "curl $*" >> "$STUB_LOG"
    [ "$(cat "$STUB_STATE")" = true ] || exit 7
    count=$(cat "$STUB_HEALTH_COUNT")
    count=$((count + 1))
    echo "$count" > "$STUB_HEALTH_COUNT"
    [ "$count" -gt "${STUB_HEALTH_FAILURES:-0}" ] || exit 7
    exit 0
    """)

STUB_BROWSER = textwrap.dedent("""\
    #!/bin/sh
    echo "browser $*" >> "$STUB_LOG"
    exit 0
    """)


@unittest.skipUnless(os.name == "posix", "runtime checks execute run.sh")
class RunShRuntimeTest(unittest.TestCase):
    """Execute run.sh against stub docker/curl/browser commands."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ppm-launcher-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.log = self.tmp / "log"
        self.log.touch()
        self.state = self.tmp / "state"
        self.state.write_text("missing")
        self.health_count = self.tmp / "health-count"
        self.health_count.write_text("0")
        for name, body in (
            ("docker", STUB_DOCKER),
            ("curl", STUB_CURL),
            ("open", STUB_BROWSER),
            ("xdg-open", STUB_BROWSER),
        ):
            stub = self.bin / name
            stub.write_text(body)
            stub.chmod(0o755)

    def run_launcher(self, env=None, with_docker=True):
        if with_docker:
            path = f"{self.bin}:{os.environ.get('PATH', '')}"
        else:
            # Only the stub directory, without the docker stub: the real
            # docker CLI on the host PATH must not leak into this test.
            (self.bin / "docker").unlink()
            path = str(self.bin)
        full_env = {
            "PATH": path,
            "HOME": str(self.tmp),
            "STUB_LOG": str(self.log),
            "STUB_STATE": str(self.state),
            "STUB_HEALTH_COUNT": str(self.health_count),
            **(env or {}),
        }
        return subprocess.run(
            ["/bin/sh", str(RUN_SH)], env=full_env,
            capture_output=True, text=True, timeout=120,
        )

    def log_lines(self):
        return self.log.read_text().splitlines()

    def wait_for_browser_log(self):
        # xdg-open is launched in the background on Linux; give the stub a
        # moment to append its log line after the launcher exits.
        import time
        for _ in range(50):
            if any(line.startswith("browser ") for line in self.log_lines()):
                return
            time.sleep(0.1)

    def test_fresh_start_creates_container_and_opens_browser_last(self):
        result = self.run_launcher(env={"STUB_HEALTH_FAILURES": "2"})
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = self.log_lines()
        run_line = next(line for line in lines if line.startswith("docker run"))
        self.assertIn(f"-v {VOLUME}:/data", run_line)
        self.assertIn("-p 127.0.0.1:8000:8000", run_line)
        self.assertIn(f"--name {CONTAINER}", run_line)
        self.assertIn(IMAGE_PREFIX + "latest", run_line)
        self.assertIn(f"docker volume create {VOLUME}", lines)
        # The browser opens exactly once, strictly after a successful probe.
        self.wait_for_browser_log()
        lines = self.log_lines()
        run_index = lines.index(run_line)
        browser_calls = [i for i, line in enumerate(lines) if line.startswith("browser ")]
        self.assertEqual(len(browser_calls), 1)
        self.assertIn("http://127.0.0.1:8000", lines[browser_calls[0]])
        probes = [i for i, line in enumerate(lines) if line.startswith("curl ")]
        self.assertEqual(len(probes), 3)  # Two failing polls, then success.
        self.assertGreater(browser_calls[0], probes[-1])
        self.assertGreater(probes[0], run_index)

    def test_rerun_with_running_container_is_a_safe_noop(self):
        self.state.write_text("true")
        result = self.run_launcher()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.wait_for_browser_log()
        joined = "\n".join(self.log_lines())
        self.assertNotIn("docker run", joined)
        self.assertNotIn("docker start", joined)
        self.assertIn("browser ", joined)
        self.assertIn("reusing", result.stdout)

    def test_rerun_with_stopped_container_starts_it_without_recreating(self):
        self.state.write_text("false")
        result = self.run_launcher()
        self.assertEqual(result.returncode, 0, result.stderr)
        joined = "\n".join(self.log_lines())
        self.assertIn(f"docker start {CONTAINER}", joined)
        self.assertNotIn("docker run", joined)
        self.assertIn("all data is kept", result.stdout)

    def test_custom_port_is_used_for_publish_probe_and_browser(self):
        result = self.run_launcher(env={"PPM_PORT": "18008"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.wait_for_browser_log()
        joined = "\n".join(self.log_lines())
        self.assertIn("-p 127.0.0.1:18008:8000", joined)
        self.assertIn("http://127.0.0.1:18008/api/health", joined)
        self.assertIn("browser http://127.0.0.1:18008", joined)

    def test_missing_docker_fails_clearly_before_any_action(self):
        result = self.run_launcher(with_docker=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Docker", result.stderr)
        self.assertNotIn("browser ", self.log.read_text())

    def test_stopped_daemon_fails_clearly(self):
        result = self.run_launcher(env={"STUB_INFO_EXIT": "1"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("daemon", result.stderr)
        self.assertNotIn("docker run", self.log.read_text())

    def test_health_timeout_is_bounded_and_reported(self):
        result = self.run_launcher(
            env={"STUB_HEALTH_FAILURES": "1000", "PPM_WAIT_SECONDS": "2"},
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("did not become healthy within 2 seconds", result.stderr)
        self.assertNotIn("browser ", self.log.read_text())


if __name__ == "__main__":
    unittest.main()
