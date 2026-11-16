import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import recomplauncher as launcher


class _FakeKeyring:
    """Stands in for the OS credential store."""

    class errors:
        PasswordDeleteError = KeyError

    def __init__(self):
        self.store = {}

    def get_password(self, service, name):
        return self.store.get(name)

    def set_password(self, service, name, value):
        self.store[name] = value

    def delete_password(self, service, name):
        del self.store[name]


class _TempDataCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        launcher.LOAD_WARNINGS.clear()
        self.addCleanup(launcher.LOAD_WARNINGS.clear)


class CorruptDataFiles(_TempDataCase):
    def test_unreadable_file_is_kept_aside_and_reported(self):
        path = self.tmp / "games.json"
        path.write_text("{not json", encoding="utf-8")
        self.assertIsNone(launcher.load_json(path, None, expect=list))
        backups = list(self.tmp.glob("games.json.corrupt-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), "{not json")
        self.assertEqual(len(launcher.LOAD_WARNINGS), 1)

    def test_wrong_top_level_type_counts_as_corrupt(self):
        path = self.tmp / "games.json"
        path.write_text('{"a": 1}', encoding="utf-8")
        self.assertEqual(launcher.load_json(path, [], expect=list), [])
        self.assertTrue(list(self.tmp.glob("games.json.corrupt-*")))

    def test_missing_file_is_not_a_problem(self):
        self.assertEqual(launcher.load_json(self.tmp / "nope.json", 7), 7)
        self.assertEqual(launcher.LOAD_WARNINGS, [])


class ApiKeyStorage(_TempDataCase):
    def setUp(self):
        super().setUp()
        self.file = self.tmp / "settings.json"
        self.keyring = _FakeKeyring()
        for target, value in (("SETTINGS_FILE", self.file), ("keyring", self.keyring),
                              ("_stored_secrets", {})):
            patcher = mock.patch.object(launcher, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _on_disk(self):
        return json.loads(self.file.read_text(encoding="utf-8"))

    def test_keys_go_to_the_credential_store_not_the_file(self):
        settings = launcher.load_settings()
        settings["sgdb_api_key"] = "sgdb-secret"
        settings["ra_api_key"] = "ra-secret"
        launcher.save_settings(settings)
        self.assertEqual(self.keyring.store,
                         {"sgdb_api_key": "sgdb-secret", "ra_api_key": "ra-secret"})
        self.assertNotIn("secret", self.file.read_text(encoding="utf-8"))
        self.assertEqual(launcher.load_settings()["ra_api_key"], "ra-secret")

    def test_key_left_in_the_file_by_an_older_version_is_moved(self):
        self.file.write_text(json.dumps({"sgdb_api_key": "old", "theme": "Nord"}),
                             encoding="utf-8")
        settings = launcher.load_settings()
        self.assertEqual(settings["sgdb_api_key"], "old")
        self.assertEqual(self.keyring.store["sgdb_api_key"], "old")
        self.assertNotIn("sgdb_api_key", self._on_disk())
        self.assertEqual(self._on_disk()["theme"], "Nord")

    def test_clearing_a_key_removes_it_from_the_store(self):
        settings = launcher.load_settings()
        settings["ra_api_key"] = "x"
        launcher.save_settings(settings)
        settings["ra_api_key"] = ""
        launcher.save_settings(settings)
        self.assertEqual(self.keyring.store, {})

    def test_without_a_credential_store_the_key_stays_in_the_file(self):
        with mock.patch.object(launcher, "keyring", None):
            settings = launcher.load_settings()
            settings["ra_api_key"] = "plain"
            launcher.save_settings(settings)
            self.assertEqual(self._on_disk()["ra_api_key"], "plain")
            self.assertEqual(launcher.load_settings()["ra_api_key"], "plain")
            self.assertFalse(launcher.secrets_in_keyring())


class FolderScan(_TempDataCase):
    def _touch(self, rel, data=b"", mode=None):
        path = self.tmp / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        if mode is not None:
            path.chmod(mode)
        return path

    def _names(self, platform):
        return [p.name for p in launcher.find_game_executables(self.tmp, platform)]

    def test_helpers_are_skipped_but_known_names_always_win(self):
        self._touch("soh/soh.exe")
        self._touch("soh/setup.exe")
        self._touch("bh/bh-launcher.exe")       # "launcher" is blacklisted
        self.assertEqual(self._names("win32"), ["bh-launcher.exe", "soh.exe"])

    @unittest.skipIf(os.name == "nt", "needs POSIX executable bits")
    def test_linux_finds_extensionless_binaries_but_not_libraries(self):
        elf = b"\x7fELF" + b"\0" * 12
        self._touch("game/2s2h", elf, 0o755)
        self._touch("game/libfoo.so.1", elf, 0o755)
        self._touch("game/notes", b"hello", 0o755)
        self._touch("game/data.bin", elf, 0o644)
        self.assertEqual(self._names("linux"), ["2s2h"])
        self.assertEqual(self._names("win32"), [])

    def test_known_name_matches_without_the_exe_suffix(self):
        match = launcher.identify_exe("/games/oot/soh")
        self.assertEqual(match["platform"], "Ship of Harkinian")

    def test_triforce_is_identified(self):
        match = launcher.identify_exe(r"C:\Games\Triforce\Triforce.exe".replace("\\", "/"))
        self.assertEqual(match["platform"], "Triforce")
        self.assertEqual(match["title"], "The Legend of Zelda: Ocarina of Time")


class _Response:
    def __init__(self, status=200, payload=None, headers=None, chunks=()):
        self.status_code = status
        self._payload = payload or {}
        self.headers = headers or {}
        self._chunks = chunks

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=0):
        yield from self._chunks

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class UpdateChecks(_TempDataCase):
    def _run(self, jobs, responses):
        worker = launcher.UpdateWorker(jobs, cache_file=self.tmp / "cache.json")
        seen, limited, done = [], [], []
        worker.one.connect(lambda gid, tag: seen.append((gid, tag)))
        worker.rate_limited.connect(limited.append)
        worker.done.connect(done.append)
        with mock.patch.object(launcher.requests, "get",
                               side_effect=responses) as get:
            worker.run()
        return seen, limited, done, get

    def test_games_sharing_a_repo_cost_one_request(self):
        seen, _, done, get = self._run(
            [("a", "Owner/Repo"), ("b", "owner/repo")],
            [_Response(payload={"tag_name": "v2"}, headers={"ETag": '"abc"'})])
        self.assertEqual(seen, [("a", "v2"), ("b", "v2")])
        self.assertEqual(done, [2])
        self.assertEqual(get.call_count, 1)

    def test_unchanged_release_is_answered_from_the_cache(self):
        self._run([("a", "o/r")],
                  [_Response(payload={"tag_name": "v2"}, headers={"ETag": '"abc"'})])
        seen, _, _, get = self._run([("a", "o/r")], [_Response(status=304)])
        self.assertEqual(seen, [("a", "v2")])
        self.assertEqual(get.call_args.kwargs["headers"]["If-None-Match"], '"abc"')

    def test_rate_limit_stops_the_run_and_is_reported(self):
        seen, limited, done, get = self._run(
            [("a", "o/one"), ("b", "o/two")],
            [_Response(status=403, headers={"x-ratelimit-remaining": "0",
                                            "x-ratelimit-reset": "1700000000"})])
        self.assertEqual(seen, [])
        self.assertEqual(len(limited), 1)
        self.assertEqual(done, [0])
        self.assertEqual(get.call_count, 1)


class Downloads(_TempDataCase):
    RELEASE = {"tag_name": "v1", "assets": [
        {"name": "game-windows-x64.zip", "browser_download_url": "https://x/y.zip"}]}

    def _run(self, download_response):
        worker = launcher.DownloadWorker("o/r", str(self.tmp))
        finished, failed = [], []
        worker.finished.connect(lambda path, tag: finished.append((path, tag)))
        worker.failed.connect(failed.append)
        with mock.patch.object(launcher.requests, "get", side_effect=[
                _Response(payload=self.RELEASE), download_response]), \
                mock.patch.object(launcher.sys, "platform", "win32"):
            worker.run()
        return finished, failed

    def test_complete_download_lands_under_its_real_name(self):
        finished, failed = self._run(
            _Response(headers={"content-length": "6"}, chunks=[b"abc", b"def"]))
        self.assertEqual(failed, [])
        dest = self.tmp / "game-windows-x64.zip"
        self.assertEqual(finished, [(str(dest), "v1")])
        self.assertEqual(dest.read_bytes(), b"abcdef")
        self.assertEqual([p.name for p in self.tmp.iterdir()], [dest.name])

    def test_truncated_download_leaves_nothing_behind(self):
        finished, failed = self._run(
            _Response(headers={"content-length": "600"}, chunks=[b"abc"]))
        self.assertEqual(finished, [])
        self.assertEqual(len(failed), 1)
        self.assertEqual(list(self.tmp.iterdir()), [])


class LaunchArguments(unittest.TestCase):
    def test_quoted_arguments_stay_together(self):
        self.assertEqual(
            launcher.build_launch_command("/g/soh", '--mod "my mods/a b" -x', windows=False),
            ["/g/soh", "--mod", "my mods/a b", "-x"])

    def test_no_arguments(self):
        self.assertEqual(launcher.build_launch_command("/g/soh", "", windows=False),
                         ["/g/soh"])

    def test_windows_keeps_the_arguments_as_typed(self):
        self.assertEqual(
            launcher.build_launch_command(r"C:\My Games\soh.exe", r'--dir "C:\a b"',
                                          windows=True),
            r'"C:\My Games\soh.exe" --dir "C:\a b"')

    def test_unbalanced_quote_is_an_error(self):
        with self.assertRaises(ValueError):
            launcher.build_launch_command("/g/soh", '--mod "oops', windows=False)


if __name__ == "__main__":
    unittest.main()
