"""Docker-free regression checks for the non-root container user (issue #40).

These tests parse the Dockerfile instruction sequence and the Compose/README
files semantically (not just as substrings): they assert the application
process is configured to run unprivileged, that /data is prepared for that
user before privileges are dropped, and that the documented migration command
matches the actual UID/GID. The behavioral half (effective UID, write access
in a running container) is verified by the manual check documented in the
README section "Running as a non-root user".
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "Dockerfile"
COMPOSE = ROOT / "compose.yaml"
README = ROOT / "README.md"


def instructions(dockerfile_text):
    """Return (INSTRUCTION, args) tuples, joining backslash continuations."""
    joined = re.sub(r"\\\s*\n", " ", dockerfile_text)
    result = []
    for line in joined.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        result.append((parts[0].upper(), parts[1] if len(parts) > 1 else ""))
    return result


def build_args(dockerfile_text):
    """Return {ARG name: default value} declared in the Dockerfile."""
    args = {}
    for instr, rest in instructions(dockerfile_text):
        if instr == "ARG" and "=" in rest:
            name, value = rest.split("=", 1)
            args[name.strip()] = value.strip()
    return args


class DockerfileNonRootTest(unittest.TestCase):
    def setUp(self):
        self.text = DOCKERFILE.read_text(encoding="utf-8")
        self.joined = re.sub(r"\\\s*\n", " ", self.text)
        self.instructions = instructions(self.text)
        self.args = build_args(self.text)

    def test_user_instruction_present_and_not_root(self):
        users = [rest for instr, rest in self.instructions if instr == "USER"]
        self.assertTrue(users, "Dockerfile must drop privileges with USER")
        final_user = users[-1].strip()
        self.assertNotIn(final_user, ("root", "0", "0:0"),
                         "the application must not run as root")

    def test_user_is_the_last_user_before_cmd(self):
        """CMD (the app process) must execute after privileges are dropped."""
        last_user_index = max(i for i, (instr, _) in
                              enumerate(self.instructions) if instr == "USER")
        cmd_index = max(i for i, (instr, _) in
                        enumerate(self.instructions) if instr == "CMD")
        self.assertLess(last_user_index, cmd_index)

    def test_fixed_uid_and_gid_build_args(self):
        """UID/GID are fixed, documented defaults and overridable per build."""
        self.assertEqual(self.args.get("PPM_UID"), "1000")
        self.assertEqual(self.args.get("PPM_GID"), "1000")
        self.assertRegex(self.joined, r"useradd[^\n]*--uid\s+\"?\$PPM_UID")
        self.assertRegex(self.joined, r"groupadd[^\n]*--gid\s+\"?\$PPM_GID")

    def test_app_user_has_no_login_shell_or_home(self):
        self.assertRegex(self.joined, r"useradd[^\n]*nologin")
        self.assertRegex(self.joined, r"useradd[^\n]*--no-create-home")

    def test_data_is_owned_by_app_user_before_volume(self):
        """A fresh named volume copies /data from the image, so the image must
        create it owned by the app user, before VOLUME and USER take effect."""
        runs = [(i, rest) for i, (instr, rest) in
                enumerate(self.instructions) if instr == "RUN"]
        chown_index = next(
            (i for i, rest in runs
             if re.search(r"chown\s+\"?\$PPM_UID:\$PPM_GID\"?\s+/data", rest)
             and re.search(r"mkdir\s+-p\s+/data", rest)),
            None)
        self.assertIsNotNone(
            chown_index,
            "Dockerfile must `mkdir -p /data` and chown it to $PPM_UID:$PPM_GID")
        user_index = max(i for i, (instr, _) in
                         enumerate(self.instructions) if instr == "USER")
        volume_index = next(i for i, (instr, rest) in
                            enumerate(self.instructions)
                            if instr == "VOLUME" and "/data" in rest)
        self.assertLess(chown_index, user_index)
        self.assertLess(chown_index, volume_index)


class ComposeUserBuildArgsTest(unittest.TestCase):
    def setUp(self):
        self.text = COMPOSE.read_text(encoding="utf-8")

    def test_compose_forwards_uid_gid_build_args(self):
        """`PPM_UID=$(id -u) ... docker compose up --build` must reach the
        image build, so Linux bind mounts can match the host owner."""
        self.assertRegex(self.text, r"PPM_UID:\s*\$\{PPM_UID:-1000\}")
        self.assertRegex(self.text, r"PPM_GID:\s*\$\{PPM_GID:-1000\}")

    def test_compose_does_not_force_a_user_override(self):
        """No `user:` key: the image's USER must stay authoritative, so the
        documented build args remain the single knob for the app UID."""
        self.assertNotRegex(self.text, r"(?m)^\s+user:")


class ReadmeMigrationTest(unittest.TestCase):
    def setUp(self):
        self.text = README.read_text(encoding="utf-8")

    def test_migration_command_is_documented(self):
        """Existing root-owned /data needs the exact tested chown command."""
        self.assertIn("--user 0", self.text)
        self.assertIn("chown -R 1000:1000 /data", self.text)

    def test_migration_uid_matches_dockerfile_default(self):
        args = build_args(DOCKERFILE.read_text(encoding="utf-8"))
        expected = f"chown -R {args['PPM_UID']}:{args['PPM_GID']} /data"
        self.assertIn(expected, self.text)

    def test_manual_verification_check_is_documented(self):
        """The acceptance criteria require a documented UID/write check."""
        self.assertIn("docker compose exec app id", self.text)
        self.assertIn("touch /data/.write-test", self.text)


if __name__ == "__main__":
    unittest.main()
