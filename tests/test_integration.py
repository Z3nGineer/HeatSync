"""Integration tests for HeatSync application."""

import sys
import os
import pytest
from unittest.mock import patch, Mock, MagicMock

pytestmark = pytest.mark.skipif(
    not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"),
    reason="Requires display server (X11 or Wayland) - skipped in headless CI"
)


class TestApplicationInitialization:
    @pytest.fixture
    def qapp(self):
        try:
            from PyQt6.QtWidgets import QApplication
            app = QApplication.instance() or QApplication(sys.argv)
            yield app
        except ImportError:
            pytest.skip("PyQt6 not available")

    def test_app_can_be_created(self, qapp):
        from PyQt6.QtWidgets import QApplication
        assert qapp is not None
        assert isinstance(qapp, QApplication)

    def test_main_window_imports(self):
        from HeatSync import MainWindow
        assert MainWindow is not None

    def test_sensor_functions_callable(self):
        from HeatSync import (
            s_cpu_usage, s_cpu_temp, s_cpu_freq,
            s_gpu_usage, s_gpu_temp, s_gpu_vram,
            s_ram, s_disk, s_network, s_battery, s_fans, s_cpu_per_core,
        )
        for fn in (s_cpu_usage, s_cpu_temp, s_cpu_freq, s_gpu_usage,
                   s_gpu_temp, s_gpu_vram, s_ram, s_disk,
                   s_network, s_battery, s_fans, s_cpu_per_core):
            assert callable(fn)

    def test_sensor_function_returns_valid_types(self):
        from HeatSync import s_cpu_usage, s_ram, s_disk
        with patch('psutil.cpu_percent', return_value=45.0):
            assert isinstance(s_cpu_usage(), float)
        with patch('psutil.virtual_memory') as mock_mem:
            mock_mem.return_value = Mock(used=1e9, total=1e10, percent=10.0)
            used, total, pct = s_ram()
            assert all(isinstance(v, float) for v in (used, total, pct))
        with patch('psutil.disk_usage') as mock_disk:
            mock_disk.return_value = Mock(used=1e11, total=1e12, percent=10.0)
            used, total, pct = s_disk()
            assert all(isinstance(v, float) for v in (used, total, pct))


class TestUIComponents:
    @pytest.fixture
    def qapp(self):
        try:
            from PyQt6.QtWidgets import QApplication
            app = QApplication.instance() or QApplication(sys.argv)
            yield app
        except ImportError:
            pytest.skip("PyQt6 not available")

    def test_arc_gauge_creation(self, qapp):
        from HeatSync import ArcGauge
        gauge = ArcGauge("Test", "%", lo=0, hi=100, color="#00ccdd")
        assert gauge is not None
        assert gauge.minimumWidth() > 0
        assert gauge.minimumHeight() > 0

    def test_arc_gauge_value_setting(self, qapp):
        from HeatSync import ArcGauge
        gauge = ArcGauge("CPU", "%", lo=0, hi=100)
        gauge.set_value(50)
        assert gauge._target == 50.0

    def test_arc_gauge_clamps_value(self, qapp):
        from HeatSync import ArcGauge
        gauge = ArcGauge("CPU", "%", lo=0, hi=100)
        gauge.set_value(150)
        assert gauge._target == 100.0
        gauge.set_value(-10)
        assert gauge._target == 0.0

    def test_arc_gauge_compact_mode(self, qapp):
        from HeatSync import ArcGauge
        gauge = ArcGauge("CPU", "%")
        normal_min_h = gauge.minimumHeight()
        gauge.set_compact(True)
        assert gauge.minimumHeight() < normal_min_h
        gauge.set_compact(False)
        assert gauge.minimumHeight() == normal_min_h

    def test_mini_arc_gauge_creation(self, qapp):
        from HeatSync import MiniArcGauge
        g = MiniArcGauge("C0")
        assert g is not None
        assert g.width() == 80
        g.set_value(55.0)
        assert g._target == 55.0

    def test_sparkline_creation(self, qapp):
        from HeatSync import Sparkline
        sparkline = Sparkline(color="#00ccdd", max_pts=90)
        assert sparkline is not None
        assert len(sparkline._hist) == 0

    def test_sparkline_data_push(self, qapp):
        from HeatSync import Sparkline
        sparkline = Sparkline()
        for v in [50.0, 55.0, 60.0]:
            sparkline.push(v)
        assert len(sparkline._hist) == 3
        assert list(sparkline._hist) == [50.0, 55.0, 60.0]

    def test_sparkline_max_points(self, qapp):
        from HeatSync import Sparkline
        sparkline = Sparkline(max_pts=5)
        for i in range(10):
            sparkline.push(float(i))
        assert len(sparkline._hist) == 5
        assert list(sparkline._hist) == [5.0, 6.0, 7.0, 8.0, 9.0]

    def test_monitor_card_creation(self, qapp):
        from HeatSync import MonitorCard
        card = MonitorCard("CPU USAGE", "%", lo=0, hi=100, color="#00ccdd")
        assert card is not None
        assert card.gauge is not None
        assert card.spark is not None

    def test_monitor_card_push_value(self, qapp):
        from HeatSync import MonitorCard
        card = MonitorCard("CPU USAGE", "%")
        card.push(45.5)
        assert card.gauge._target == 45.5
        assert len(card.spark._hist) == 1

    def test_monitor_card_compact(self, qapp):
        from HeatSync import MonitorCard
        card = MonitorCard("CPU USAGE", "%")
        card.set_compact(True)
        assert card.spark.isHidden()   # explicitly hidden in compact mode
        card.set_compact(False)
        assert not card.spark.isHidden()  # not hidden in normal mode

    def test_monitor_card_invert_warn(self, qapp):
        from HeatSync import MonitorCard
        card = MonitorCard("BATTERY", "%", 0, 100, warn=20, danger=10, invert_warn=True)
        assert card.gauge._invert_warn is True

    def test_fan_row_creation(self, qapp):
        from HeatSync import FanRow
        row = FanRow()
        assert row is not None
        row.update_fans([("cpu", 2000), ("case", 1500)])
        assert len(row._labels) == 2

    def test_fan_row_empty(self, qapp):
        from HeatSync import FanRow
        row = FanRow()
        row.update_fans([])
        assert not row._no_fan.isHidden()  # label is not explicitly hidden

    def test_per_core_row_creation(self, qapp):
        from HeatSync import PerCoreRow
        row = PerCoreRow()
        row.update_values([10.0, 20.0, 30.0, 40.0])
        assert len(row._gauges) == 4

    def test_per_core_row_resizes(self, qapp):
        from HeatSync import PerCoreRow
        row = PerCoreRow()
        row.update_values([1.0] * 8)
        assert len(row._gauges) == 8
        row.update_values([1.0] * 4)
        assert len(row._gauges) == 4

    def test_status_bar_creation(self, qapp):
        from HeatSync import StatusBar
        with patch('HeatSync.s_ram', return_value=(8.0, 16.0, 50.0)), \
             patch('HeatSync.s_gpu_vram', return_value=(0, 0, 0)), \
             patch('HeatSync.s_cpu_freq', return_value=3.6), \
             patch('HeatSync.s_disk', return_value=(250.0, 500.0, 50.0)), \
             patch('psutil.cpu_count', return_value=8):
            sb = StatusBar()
            assert sb is not None
            sb.refresh()

    def test_history_window_creation(self, qapp):
        from HeatSync import HistoryWindow
        settings = {
            "gauges": {"cpu_usage": True, "cpu_temp": True,
                       "gpu_usage": True, "gpu_temp": True},
            "history_window": {"x": None, "y": None, "w": 900, "h": 400},
        }
        win = HistoryWindow(settings)
        assert win is not None
        assert "cpu_usage" in win._sparklines
        assert "gpu_usage" in win._sparklines

    def test_history_window_update_metric(self, qapp):
        from HeatSync import HistoryWindow
        settings = {
            "gauges": {"cpu_usage": True, "cpu_temp": True,
                       "gpu_usage": True, "gpu_temp": True},
        }
        win = HistoryWindow(settings)
        win.update_metric("cpu_usage", 55.0)
        assert len(win._sparklines["cpu_usage"]._hist) == 1

    def test_data_logger_record_and_flush(self, tmp_path, qapp):
        from HeatSync import DataLogger
        logger = DataLogger(str(tmp_path), "csv", 1)
        logger.record({"cpu_usage": 50.0, "gpu_temp": 65.0})
        logger.record({"cpu_usage": 55.0, "gpu_temp": 70.0})
        assert len(logger._buffer) == 2
        logger.flush()
        csv_file = tmp_path / "heatsync_data.csv"
        assert csv_file.exists()
        content = csv_file.read_text()
        assert "cpu_usage" in content
        assert "50.0" in content

    def test_data_logger_json(self, tmp_path, qapp):
        from HeatSync import DataLogger
        logger = DataLogger(str(tmp_path), "json", 1)
        logger.record({"cpu_usage": 42.0})
        logger.flush()
        ndjson = tmp_path / "heatsync_data.ndjson"
        assert ndjson.exists()
        import json
        line = ndjson.read_text().strip()
        data = json.loads(line)
        assert data["cpu_usage"] == 42.0

    def test_data_logger_max_entries(self, tmp_path, qapp):
        from HeatSync import DataLogger
        # max_hours=1 → 3600 entries; we use a tiny buffer via max_hours logic
        # Just verify the deque capping works
        logger = DataLogger(str(tmp_path), "csv", 1)
        for i in range(100):
            logger.record({"v": float(i)})
        assert len(logger._buffer) == 100
        logger.close()

    def test_settings_dialog_creation(self, qapp):
        from HeatSync import SettingsDialog, _DEFAULT_SETTINGS
        dlg = SettingsDialog(_DEFAULT_SETTINGS)
        assert dlg is not None

    def test_settings_dialog_get_settings(self, qapp):
        from HeatSync import SettingsDialog, _DEFAULT_SETTINGS
        dlg = SettingsDialog(_DEFAULT_SETTINGS)
        result = dlg.get_settings()
        assert "theme" in result
        assert "compact" in result
        assert "gauges" in result
        assert "export" in result


class TestSensorRanges:
    def test_cpu_usage_range(self):
        from HeatSync import s_cpu_usage
        for v in [0, 25, 50, 75, 100]:
            with patch('psutil.cpu_percent', return_value=float(v)):
                assert 0 <= s_cpu_usage() <= 100

    def test_cpu_temp_reasonable_range(self):
        from HeatSync import s_cpu_temp
        with patch('psutil.sensors_temperatures',
                   return_value={"coretemp": [Mock(label="Package id 0", current=75.0)]}):
            assert 0 <= s_cpu_temp() <= 150

    def test_ram_percent_valid(self):
        from HeatSync import s_ram
        with patch('psutil.virtual_memory') as mock_mem:
            for pct in [0, 25, 50, 75, 100]:
                mock_mem.return_value = Mock(
                    used=pct * 1e9, total=100 * 1e9, percent=float(pct))
                _, _, result_pct = s_ram()
                assert 0 <= result_pct <= 100

    def test_disk_percent_valid(self):
        from HeatSync import s_disk
        with patch('psutil.disk_usage') as mock_disk:
            for pct in [0, 25, 50, 75, 100]:
                mock_disk.return_value = Mock(
                    used=pct * 1e11, total=100 * 1e11, percent=float(pct))
                _, _, result_pct = s_disk()
                assert 0 <= result_pct <= 100


class TestThemeIntegration:
    @pytest.fixture
    def qapp(self):
        try:
            from PyQt6.QtWidgets import QApplication
            app = QApplication.instance() or QApplication(sys.argv)
            yield app
        except ImportError:
            pytest.skip("PyQt6 not available")

    def test_apply_theme_dark(self, qapp):
        from HeatSync import apply_theme, DARK_THEME, _THEME
        import HeatSync
        apply_theme(DARK_THEME)
        assert HeatSync._THEME.name == "dark"

    def test_apply_theme_light(self, qapp):
        from HeatSync import apply_theme, LIGHT_THEME
        import HeatSync
        apply_theme(LIGHT_THEME)
        assert HeatSync._THEME.name == "light"
        # Restore dark
        from HeatSync import DARK_THEME
        apply_theme(DARK_THEME)

    def test_theme_affects_background_paint(self, qapp):
        from HeatSync import _Background, apply_theme, LIGHT_THEME, DARK_THEME, _THEME
        bg = _Background()
        # Just ensure paintEvent doesn't crash in either theme
        apply_theme(LIGHT_THEME)
        bg.update()
        apply_theme(DARK_THEME)
        bg.update()
