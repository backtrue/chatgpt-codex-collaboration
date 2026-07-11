import importlib.util
import os
from pathlib import Path
import unittest


SCRIPT = Path(__file__).parents[1] / "scripts" / "browser-use-transport.py"
SPEC = importlib.util.spec_from_file_location("browser_use_transport", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class BrowserUseTransportTests(unittest.TestCase):
    def test_prompt_fingerprint_is_stable(self) -> None:
        self.assertEqual(MODULE.fingerprint("prompt"), MODULE.fingerprint("prompt"))
        self.assertNotEqual(MODULE.fingerprint("prompt"), MODULE.fingerprint("other"))

    def test_required_rejects_missing_environment_value(self) -> None:
        previous = os.environ.pop("TEST_BROWSER_TRANSPORT_REQUIRED", None)
        try:
            with self.assertRaisesRegex(RuntimeError, "missing_test_browser_transport_required"):
                MODULE.required("TEST_BROWSER_TRANSPORT_REQUIRED")
        finally:
            if previous is not None:
                os.environ["TEST_BROWSER_TRANSPORT_REQUIRED"] = previous

    def test_integer_env_rejects_non_positive_value(self) -> None:
        previous = os.environ.get("TEST_BROWSER_TRANSPORT_POLL")
        os.environ["TEST_BROWSER_TRANSPORT_POLL"] = "0"
        try:
            with self.assertRaisesRegex(RuntimeError, "invalid_test_browser_transport_poll"):
                MODULE.integer_env("TEST_BROWSER_TRANSPORT_POLL", 60)
        finally:
            if previous is None:
                os.environ.pop("TEST_BROWSER_TRANSPORT_POLL", None)
            else:
                os.environ["TEST_BROWSER_TRANSPORT_POLL"] = previous


if __name__ == "__main__":
    unittest.main()
