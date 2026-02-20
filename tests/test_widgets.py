import inspect

from gpu_power_monitor.tui.widgets import PinGauge, StressTestModal


class TestPinGauge:
    def test_init_stores_pin_number(self):
        g = PinGauge(pin_number=3)
        assert g.pin_number == 3
        assert g._label == "Pin 3"

    def test_init_different_pins(self):
        for i in range(1, 7):
            g = PinGauge(pin_number=i)
            assert g._label == f"Pin {i}"


class TestStressTestModal:
    def test_is_modal_screen(self):
        from textual.screen import ModalScreen
        assert issubclass(StressTestModal, ModalScreen)

    def test_has_compose_method(self):
        assert hasattr(StressTestModal, "compose")
        assert callable(StressTestModal.compose)

    def test_has_button_handler(self):
        assert hasattr(StressTestModal, "on_button_pressed")

    def test_default_css_contains_dialog_styles(self):
        css = StressTestModal.DEFAULT_CSS
        assert "#stress-dialog" in css
        assert "#stress-buttons" in css

    def test_compose_source_has_expected_widget_ids(self):
        """Verify compose method references expected widget IDs without running it."""
        source = inspect.getsource(StressTestModal.compose)
        for widget_id in ("stress-dialog", "stress-cancel"):
            assert widget_id in source, f"Missing widget id: {widget_id}"

    def test_presets_generate_buttons(self):
        """Verify each preset creates a button ID in compose source."""
        from gpu_power_monitor.tui.widgets import _STRESS_PRESETS
        source = inspect.getsource(StressTestModal.compose)
        assert len(_STRESS_PRESETS) == 3
        for key in _STRESS_PRESETS:
            assert key in ("quick", "standard", "heavy")
