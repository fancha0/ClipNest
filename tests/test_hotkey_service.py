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


class _FakeHotKey:
    """Mimics pynput.keyboard.HotKey's internal pressed-key set."""

    def __init__(self, state: set[str]) -> None:
        self._state = set(state)


class HotkeyPhantomTriggerTests(unittest.TestCase):
    """Lost key-release events (lock screen / sleep) leave stale state in
    pynput, so an unrelated keypress can complete the combination."""

    def _service_with_state(self, state: set[str]) -> tuple[HotkeyService, _FakeHotKey]:
        service = HotkeyService("Ctrl+Shift+V")
        hotkey = _FakeHotKey(state)
        listener = mock.Mock()
        listener._hotkeys = [hotkey]
        service._listener = listener
        return service, hotkey

    def test_required_modifiers_parsed(self) -> None:
        self.assertEqual(HotkeyService("Ctrl+Shift+V").required_modifiers(), ["Ctrl", "Shift"])
        self.assertEqual(HotkeyService("Alt+F8").required_modifiers(), ["Alt"])
        self.assertEqual(HotkeyService("Win+V").required_modifiers(), ["Win"])

    def test_trigger_emits_when_modifiers_physically_held(self) -> None:
        service, _ = self._service_with_state({"shift", "v"})
        received: list[int] = []
        service.hotkey_pressed.connect(lambda: received.append(1))

        with mock.patch.object(service, "_physical_modifiers_held", return_value=True):
            service._on_hotkey_triggered()

        self.assertEqual(len(received), 1)

    def test_phantom_trigger_is_ignored_and_state_cleared(self) -> None:
        service, hotkey = self._service_with_state({"shift", "v"})
        received: list[int] = []
        service.hotkey_pressed.connect(lambda: received.append(1))

        with mock.patch.object(service, "_physical_modifiers_held", return_value=False):
            service._on_hotkey_triggered()

        self.assertEqual(received, [], "phantom trigger must not emit hotkey_pressed")
        self.assertEqual(hotkey._state, set(), "stale listener state must be cleared")

    def test_self_heal_clears_state_when_no_modifier_held(self) -> None:
        service, hotkey = self._service_with_state({"shift", "v"})

        with mock.patch.object(service, "_any_required_modifier_held", return_value=False):
            service._self_heal_stale_state()

        self.assertEqual(hotkey._state, set())

    def test_self_heal_keeps_state_while_modifier_held(self) -> None:
        service, hotkey = self._service_with_state({"shift", "v"})

        with mock.patch.object(service, "_any_required_modifier_held", return_value=True):
            service._self_heal_stale_state()

        self.assertEqual(hotkey._state, {"shift", "v"}, "must not clear during real key hold")

    def test_self_heal_noop_without_listener(self) -> None:
        service = HotkeyService("Ctrl+Shift+V")
        service._listener = None
        service._self_heal_stale_state()  # must not raise

    def test_clear_listener_state_tolerates_missing_attributes(self) -> None:
        service = HotkeyService("Ctrl+Shift+V")
        listener = mock.Mock(spec=[])
        service._listener = listener
        service._clear_listener_state()  # no _hotkeys attribute; must not raise

    def test_stop_stops_self_heal_timer(self) -> None:
        service = HotkeyService("Ctrl+Shift+V")
        service._listener = mock.Mock()
        service._self_heal_timer.start()
        service.stop()
        self.assertFalse(service._self_heal_timer.isActive())


if __name__ == "__main__":
    unittest.main()
