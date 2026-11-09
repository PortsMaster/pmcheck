import unittest

from pmcheck.llm import known_false


class KnownFalse(unittest.TestCase):
    def test_dropped(self):
        for issue, fix in [
            ("port.json runtime catalog keys must not have the .squashfs file extension.", ""),
            ("port.json uses filename extensions (.squashfs) in the runtime array.",
             "Remove the .squashfs extensions from 'weston_pkg_0.2.squashfs' so it reads 'weston_pkg_0.2'."),
            ("gptokeyb2 is invoked with the flag -x without specifying an ini config file via -c.",
             "Provide a valid gptokeyb2 ini configuration file or remove the invalid invocation parameters."),
            ("gptokeyb2 target binary name is missing the .${DEVICE_ARCH} suffix.", ""),
        ]:
            self.assertTrue(known_false({"issue": issue, "fix": fix}), issue)

    def test_kept(self):
        for issue in [
            "The script mounts godot_4.7.1.squashfs but port.json lists no runtime.",
            "gptokeyb2 kill target is 'java' but the game runs as love.",
            "The README controls table says B jumps; the .ini maps b = esc.",
        ]:
            self.assertFalse(known_false({"issue": issue}), issue)


if __name__ == "__main__":
    unittest.main()
