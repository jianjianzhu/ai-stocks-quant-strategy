import contextlib
import io
from importlib.resources import files
from pathlib import Path
import tempfile
import unittest

from ai_stocks_quant.cli import main


class PackageTests(unittest.TestCase):
    def test_resources_match_canonical_source(self):
        canonical = Path(__file__).resolve().parents[1] / "strategies/smc"
        resource = files("ai_stocks_quant").joinpath("resources", "smc")
        for source in canonical.iterdir():
            if source.is_file():
                self.assertEqual(source.read_bytes(), resource.joinpath(source.name).read_bytes())

    def test_export_contains_source_and_license_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "smc"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["export", "smc", "--output", str(destination)]), 0)
            source = (destination / "SMC_V6_strategy.pine").read_text(encoding="utf-8")
            self.assertIn("LuxAlgo", source)
            self.assertIn("CC BY-NC-SA 4.0", source)
            self.assertTrue((destination / "LICENSE.md").is_file())
            self.assertTrue((destination / "README.md").is_file())
            marker = destination / "user-edit.txt"
            marker.write_text("preserve", encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                main(["export", "smc", "--output", str(destination)])
            self.assertEqual(error.exception.code, 1)
            self.assertEqual(marker.read_text(encoding="utf-8"), "preserve")


if __name__ == "__main__":
    unittest.main()
