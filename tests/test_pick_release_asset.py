import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import recomplauncher as launcher


def _assets(*names):
    return [{"name": name} for name in names]


def _picked(names, platform):
    asset = launcher.pick_release_asset(_assets(*names), platform)
    return asset["name"] if asset else None


WORDS_CONTAINING_ARM = ("farm", "warm", "charm", "alarm", "swarm", "harmony")


class ArmIsNotAWordInsideAName(unittest.TestCase):
    """A name that merely contains the letters "arm" is not an ARM build."""

    def test_windows_picks_a_zip_whose_name_contains_arm_inside_a_word(self):
        for word in WORDS_CONTAINING_ARM:
            name = f"{word}-windows-x86_64-v1.0.zip"
            with self.subTest(name=name):
                self.assertEqual(_picked([name], "win32"), name)

    def test_linux_picks_a_tarball_whose_name_contains_arm_inside_a_word(self):
        for word in WORDS_CONTAINING_ARM:
            name = f"{word}-linux-x86_64-v1.0.tar.gz"
            with self.subTest(name=name):
                self.assertEqual(_picked([name], "linux"), name)


class ArmBuildsAreStillAvoided(unittest.TestCase):
    def test_windows_skips_arm_builds(self):
        for name in ("game-windows-arm64.zip", "game-windows-arm.zip", "game-windows-armv7.zip"):
            with self.subTest(name=name):
                self.assertIsNone(_picked([name], "win32"))

    def test_windows_prefers_the_x64_zip_beside_an_arm_zip(self):
        self.assertEqual(
            _picked(["game-windows-arm64.zip", "game-windows-x64.zip"], "win32"),
            "game-windows-x64.zip",
        )


if __name__ == "__main__":
    unittest.main()
