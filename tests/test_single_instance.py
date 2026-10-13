from __future__ import annotations

import unittest
import uuid

from clipboard_manager.services.single_instance import SingleInstance


class SingleInstanceTests(unittest.TestCase):
    def test_second_instance_detected(self) -> None:
        name = f"ClipNestTest-{uuid.uuid4().hex}"
        first = SingleInstance(name)
        try:
            self.assertFalse(first.already_running)
            second = SingleInstance(name)
            try:
                self.assertTrue(second.already_running)
            finally:
                second.release()
        finally:
            first.release()

    def test_release_allows_reacquire(self) -> None:
        name = f"ClipNestTest-{uuid.uuid4().hex}"
        first = SingleInstance(name)
        self.assertFalse(first.already_running)
        first.release()
        second = SingleInstance(name)
        try:
            self.assertFalse(second.already_running)
        finally:
            second.release()


if __name__ == "__main__":
    unittest.main()
