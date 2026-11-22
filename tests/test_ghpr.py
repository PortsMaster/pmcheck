"""ghpr.fetch() over git, against a local bare repo laid out like PortMaster-New (no network)."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pmcheck import ghpr

URL = "https://github.com/PortsMaster/PortMaster-New/pull/{}"


def git(cwd, *args):
    env = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", HOME=str(cwd), GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    return subprocess.run(["git", "-c", "init.defaultBranch=main", *args], cwd=cwd, env=env, check=True,
                          capture_output=True).stdout.decode().strip()


class GitFetch(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(self.tmp)]))
        self.bare = self.tmp / "remote.git"
        git(self.tmp, "init", "-q", "--bare", str(self.bare))
        for k in ("uploadpack.allowFilter", "uploadpack.allowAnySHA1InWant"):
            git(self.bare, "config", k, "true")
        self.wt = self.tmp / "wt"
        git(self.tmp, "init", "-q", str(self.wt))
        self.put("README.md", "root\n")
        self.put("ports/old/old.sh", "#!/bin/bash\n")
        self.commit("base")
        git(self.wt, "push", "-q", str(self.bare), "HEAD:refs/heads/main")
        self.base = git(self.wt, "rev-parse", "HEAD")
        meta = mock.patch.object(ghpr, "_meta", lambda n, strict: {"title": f"PR #{n}", "state": "open", "repo": ghpr.REPO})
        meta.start()
        self.addCleanup(meta.stop)

    def put(self, path, data):
        p = self.wt / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data if isinstance(data, bytes) else data.encode())

    def commit(self, msg):
        git(self.wt, "add", "-A")
        git(self.wt, "commit", "-q", "-m", msg)

    def pr(self, n=1):
        git(self.wt, "push", "-q", "-f", str(self.bare), f"HEAD:refs/pull/{n}/head")

    def main_moves_on(self):
        """Another port merged on main after the PR branched: must not count as part of the PR."""
        head = git(self.wt, "rev-parse", "HEAD")
        git(self.wt, "checkout", "-q", self.base)
        self.put("ports/other/other.sh", "x\n")
        self.commit("other")
        git(self.wt, "push", "-q", "-f", str(self.bare), "HEAD:refs/heads/main")
        git(self.wt, "checkout", "-q", head)

    def fetch(self, n=1, max_bytes=1 << 30):
        dest = self.tmp / "out" / "ports"
        dest.mkdir(parents=True, exist_ok=True)
        return ghpr.fetch(URL.format(n), dest, max_bytes, log=lambda m: None, remote=f"file://{self.bare}")

    def test_new_port_only_its_files(self):
        self.put("ports/game/Game.sh", "#!/bin/bash\necho hi\n")
        self.put("ports/game/game/data.bin", bytes(range(256)) * 10)
        self.commit("game")
        self.put("ports/game/.gitattributes", "* text eol=crlf\n")
        self.commit("attrs")
        self.pr()
        self.main_moves_on()
        info, dirs = self.fetch()
        self.assertEqual(info["ports"], ["game"])
        self.assertEqual(sorted(info["files"]), ["ports/game/.gitattributes", "ports/game/Game.sh", "ports/game/game/data.bin"])
        self.assertEqual([d.name for d in dirs], ["game"])
        # byte-exact: the blob's LF stays, although a checkout would write CRLF here
        self.assertEqual((dirs[0] / "Game.sh").read_bytes(), b"#!/bin/bash\necho hi\n")
        self.assertEqual((dirs[0] / "game" / "data.bin").read_bytes(), bytes(range(256)) * 10)
        self.assertFalse(any(p.name.startswith("pmcheck-git") for p in (self.tmp / "out").iterdir()))

    def test_symlink_rejected(self):
        self.put("ports/game/Game.sh", "x\n")
        os.symlink("/etc/passwd", self.wt / "ports/game/link")
        self.commit("game")
        self.pr()
        with self.assertRaisesRegex(ghpr.PRError, "symlink"):
            self.fetch()

    def test_size_limit_before_download(self):
        self.put("ports/game/big.bin", b"\0" * 5000)
        self.commit("game")
        self.pr()
        with mock.patch.object(ghpr, "_export", side_effect=AssertionError("downloaded")):
            with self.assertRaisesRegex(ghpr.PRError, "limit"):
                self.fetch(max_bytes=1000)

    def test_too_many_ports(self):
        for i in range(ghpr.MAX_PORTS + 1):
            self.put(f"ports/p{i}/p.sh", "x\n")
        self.commit("many")
        self.pr()
        with self.assertRaisesRegex(ghpr.PRError, "at most"):
            self.fetch()

    def test_only_deletes(self):
        git(self.wt, "rm", "-q", "-r", "ports/old")
        self.commit("rm")
        self.pr()
        with self.assertRaisesRegex(ghpr.PRError, "only deletes"):
            self.fetch()

    def test_missing_pr(self):
        with self.assertRaisesRegex(ghpr.PRError, "not found"):
            self.fetch(n=99)

    def test_no_git_falls_back_to_api(self):
        with mock.patch.dict(os.environ, {"PATH": str(self.tmp / "nothing")}), \
             mock.patch.object(ghpr, "_fetch_api", return_value=("api", [])) as api:
            self.assertEqual(self.fetch(), ("api", []))
            api.assert_called_once()


if __name__ == "__main__":
    unittest.main()
