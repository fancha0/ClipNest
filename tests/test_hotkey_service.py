from __future__ import annotations

import unittest
from unittest import mock

from clipboard_manager.services.hotkey_service import HotkeyService


class HotkeyServiceTests(unittest.TestCase):
    def test_normalize_valid_combo(self) -> None:
        value, error = HotkeyService.normalize_hotkey("shift+ctrl+v")
        self.assertIsNone(error)
        self.assertEqual(value, "Ctrl+Shift+V")

    def test_normalize_requires_modifier(self) -> None:
        value, error = HotkeyService.normalize_hotkey("V")
        self.assertIsNone(value)
        self.assertIsNotNone(error)

    def test_normalize_requires_primary_key(self) -> None:
        value, error = HotkeyService.normalize_hotkey("Ctrl+Shift")
        self.assertIsNone(value)
        self.assertIsNotNone(error)

    def test_normalize_rejects_multi_sequence(self) -> None:
        value, error = HotkeyService.normalize_hotkey("Ctrl+V,Ctrl+C")
        self.assertIsNone(value)
        self.assertIsNotNone(error)

    def test_special_hotkeys_parse_successfully(self) -> None:
        samples = ["Ctrl+Space", "Ctrl+PageUp", "Ctrl+F8", "Alt+Up", "Win+U"]
        for raw in samples:
            with self.subTest(raw=raw):
                normalized, error = HotkeyService.normalize_hotkey(raw)
                self.assertIsNone(error)
                self.assertIsNotNone(normalized)
                combo, combo_error = HotkeyService._build_and_validate_combo(normalized)
                self.assertIsNone(combo_error)
                self.assertIsNotNone(combo)

    def test_to_pynput_combo_win_and_ctrl_are_distinct(self) -> None:
        self.assertEqual(HotkeyService._to_pynput_combo("Win+V"), "<cmd>+v")
        self.assertEqual(HotkeyService._to_pynput_combo("Ctrl+V"), "<ctrl>+v")

    def test_start_registers_global_hotkey(self) -> None:
        service = HotkeyService("Win+U")
        listener = mock.Mock()
        with mock.patch(
            "clipboard_manager.services.hotkey_service.keyboard.GlobalHotKeys",
            return_value=listener,
        ) as mocked:
            ok = service.start()

        self.assertTrue(ok)
        self.assertIsNone(service.last_error)
        mocked.assert_called_once()
        listener.start.assert_called_once()
        registered = mocked.call_args.args[0]
        self.assertIn("<cmd>+u", registered)
        self.assertTrue(callable(registered["<cmd>+u"]))

    def test_stop_unregisters_listener(self) -> None:
        service = HotkeyService("Ctrl+Shift+V")
        listener = mock.Mock()
        service._listener = listener
        service.stop()
        listener.stop.assert_called_once()
        self.assertIsNone(service._listener)

    def test_update_hotkey_rolls_back_when_new_hotkey_fails(self) -> None:
        service = HotkeyService("Ctrl+Shift+V")
        service._listener = mock.Mock()
        service.last_error = "bad combo"

        with mock.patch.object(service, "start", side_effect=[False, True]):
            ok, err = service.update_hotkey("Ctrl+Space")

        self.assertFalse(ok)
        self.assertEqual(err, "bad combo")
        self.assertEqual(service.hotkey_text, "Ctrl+Shift+V")


if __name__ == "__main__":
    unittest.main()
