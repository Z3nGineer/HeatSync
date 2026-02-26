"""Unit tests for sensor functions."""

import sys
import os
import time
import pytest
from unittest.mock import Mock, patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestCPUSensors:
    """Tests for CPU sensor functions."""

    def test_cpu_usage_returns_percentage(self, mock_psutil):
        with patch('psutil.cpu_percent', return_value=45.0):
            from HeatSync import s_cpu_usage
            result = s_cpu_usage()
            assert 0 <= result <= 100
            assert result == 45.0

    def test_cpu_usage_zero(self):
        with patch('psutil.cpu_percent', return_value=0.0):
            from HeatSync import s_cpu_usage
            assert s_cpu_usage() == 0.0

    def test_cpu_usage_max(self):
        with patch('psutil.cpu_percent', return_value=100.0):
            from HeatSync import s_cpu_usage
            assert s_cpu_usage() == 100.0

    def test_cpu_temp_coretemp_linux(self, mock_psutil):
        mock_temps = {"coretemp": [Mock(label="Package id 0", current=65.5)]}
        with patch('psutil.sensors_temperatures', return_value=mock_temps):
            with patch('sys.platform', 'linux'):
                from HeatSync import s_cpu_temp
                assert s_cpu_temp() == 65.5

    def test_cpu_temp_returns_float(self):
        from HeatSync import s_cpu_temp
        result = s_cpu_temp()
        assert isinstance(result, float)
        assert result >= 0.0

    def test_cpu_freq_returns_ghz(self):
        with patch('psutil.cpu_freq', return_value=Mock(current=3600.0)):
            from HeatSync import s_cpu_freq
            assert s_cpu_freq() == 3.6

    def test_cpu_freq_none_returns_zero(self):
        with patch('psutil.cpu_freq', return_value=None):
            from HeatSync import s_cpu_freq
            assert s_cpu_freq() == 0.0

    def test_cpu_per_core_returns_list(self):
        mock_values = [10.0, 20.0, 30.0, 40.0]
        with patch('psutil.cpu_percent', return_value=mock_values):
            from HeatSync import s_cpu_per_core
            result = s_cpu_per_core()
            assert isinstance(result, list)
            assert all(isinstance(v, float) for v in result)

    def test_cpu_per_core_percpu_flag(self):
        """s_cpu_per_core must call cpu_percent with percpu=True."""
        with patch('psutil.cpu_percent', return_value=[5.0, 10.0]) as mock_pct:
            from HeatSync import s_cpu_per_core
            s_cpu_per_core()
            mock_pct.assert_called_once_with(percpu=True)


class TestMemorySensors:
    """Tests for memory sensor functions."""

    def test_ram_usage_valid_values(self, mock_psutil):
        mock_psutil.virtual_memory.return_value = Mock(
            used=8_000_000_000, total=16_000_000_000, percent=50.0)
        with patch('psutil.virtual_memory', return_value=mock_psutil.virtual_memory()):
            from HeatSync import s_ram
            used, total, pct = s_ram()
            assert used == pytest.approx(8.0, abs=0.01)
            assert total == pytest.approx(16.0, abs=0.01)
            assert pct == 50.0

    def test_disk_usage_valid_values(self):
        with patch('psutil.disk_usage') as mock_disk:
            mock_disk.return_value = Mock(
                used=500_000_000_000, total=1_000_000_000_000, percent=50.0)
            from HeatSync import s_disk
            used, total, pct = s_disk()
            assert used == pytest.approx(500.0, abs=0.01)
            assert total == pytest.approx(1000.0, abs=0.01)
            assert pct == pytest.approx(50.0, abs=0.1)


class TestGPUSensors:
    """Tests for GPU sensor functions."""

    def test_gpu_usage_nvidia(self):
        with patch('HeatSync.GPU_HANDLE', Mock()):
            with patch('pynvml.nvmlDeviceGetUtilizationRates') as mock_util:
                mock_util.return_value = Mock(gpu=72.0)
                from HeatSync import s_gpu_usage
                assert s_gpu_usage() == 72.0

    def test_gpu_usage_no_gpu(self):
        with patch('heatsync.sensors.GPU_HANDLE', None), \
             patch('heatsync.sensors._AMD_DEV', None), \
             patch('heatsync.sensors._INTEL_DEV', None):
            from HeatSync import s_gpu_usage
            assert s_gpu_usage() == 0.0

    def test_gpu_temp_nvidia(self):
        with patch('HeatSync.GPU_HANDLE', Mock()):
            with patch('pynvml.nvmlDeviceGetTemperature', return_value=68.0):
                from HeatSync import s_gpu_temp
                assert s_gpu_temp() == 68.0

    def test_gpu_temp_no_gpu(self):
        with patch('heatsync.sensors.GPU_HANDLE', None), \
             patch('heatsync.sensors._AMD_DEV', None), \
             patch('heatsync.sensors._INTEL_DEV', None):
            from HeatSync import s_gpu_temp
            assert s_gpu_temp() == 0.0

    def test_gpu_vram_nvidia(self):
        with patch('HeatSync.GPU_HANDLE', Mock()):
            gpu_mem = Mock()
            gpu_mem.used = 8589934592; gpu_mem.total = 10737418240
            with patch('pynvml.nvmlDeviceGetMemoryInfo', return_value=gpu_mem):
                from HeatSync import s_gpu_vram
                used, total, pct = s_gpu_vram()
                assert used == 8192
                assert total == 10240
                assert pct == pytest.approx(80.0, abs=0.1)

    def test_gpu_vram_no_gpu(self):
        with patch('heatsync.sensors.GPU_HANDLE', None), \
             patch('heatsync.sensors._AMD_DEV', None), \
             patch('heatsync.sensors._INTEL_DEV', None):
            from HeatSync import s_gpu_vram
            assert s_gpu_vram() == (0, 0, 0)


class TestNetworkSensor:
    """Tests for s_network()."""

    def setup_method(self):
        # Reset the module-level _net_prev state between tests
        import heatsync.sensors
        heatsync.sensors._net_prev = {}

    def test_first_call_returns_zeros(self):
        mock_counters = Mock(bytes_sent=1_000_000, bytes_recv=2_000_000)
        with patch('psutil.net_io_counters', return_value=mock_counters):
            from HeatSync import s_network
            up, down = s_network()
            assert up == 0.0
            assert down == 0.0

    def test_second_call_computes_delta(self):
        import heatsync.sensors
        heatsync.sensors._net_prev = {
            "t": time.monotonic() - 1.0,
            "sent": 0,
            "recv": 0,
        }
        # 1 second later: 1 MB sent, 2 MB received → 8 Mbps up, 16 Mbps down
        mock_counters = Mock(bytes_sent=1_000_000, bytes_recv=2_000_000)
        with patch('psutil.net_io_counters', return_value=mock_counters):
            from HeatSync import s_network
            up, down = s_network()
            assert up > 0.0
            assert down > 0.0
            assert down > up  # more data received than sent

    def test_returns_non_negative(self):
        import heatsync.sensors
        heatsync.sensors._net_prev = {
            "t": time.monotonic() - 1.0,
            "sent": 5_000_000,
            "recv": 5_000_000,
        }
        # Simulate counter wrap / decrease — should clamp to 0
        mock_counters = Mock(bytes_sent=0, bytes_recv=0)
        with patch('psutil.net_io_counters', return_value=mock_counters):
            from HeatSync import s_network
            up, down = s_network()
            assert up >= 0.0
            assert down >= 0.0

    def test_psutil_failure_returns_zeros(self):
        import heatsync.sensors
        heatsync.sensors._net_prev = {}
        with patch('psutil.net_io_counters', side_effect=Exception("no net")):
            from HeatSync import s_network
            up, down = s_network()
            assert up == 0.0 and down == 0.0


class TestBatterySensor:
    """Tests for s_battery()."""

    def test_battery_present(self):
        mock_bat = Mock(percent=75.0, power_plugged=False)
        with patch('psutil.sensors_battery', return_value=mock_bat):
            from HeatSync import s_battery
            result = s_battery()
            assert result is not None
            pct, charging = result
            assert pct == 75.0
            assert charging is False

    def test_battery_charging(self):
        mock_bat = Mock(percent=90.0, power_plugged=True)
        with patch('psutil.sensors_battery', return_value=mock_bat):
            from HeatSync import s_battery
            pct, charging = s_battery()
            assert pct == 90.0
            assert charging is True

    def test_no_battery_returns_none(self):
        with patch('psutil.sensors_battery', return_value=None):
            from HeatSync import s_battery
            assert s_battery() is None

    def test_exception_returns_none(self):
        with patch('psutil.sensors_battery', side_effect=Exception("no battery")):
            from HeatSync import s_battery
            assert s_battery() is None

    def test_percent_in_range(self):
        for pct in [0.0, 50.0, 100.0]:
            with patch('psutil.sensors_battery', return_value=Mock(percent=pct, power_plugged=False)):
                from HeatSync import s_battery
                result = s_battery()
                assert result is not None
                assert 0.0 <= result[0] <= 100.0


class TestFanSensor:
    """Tests for s_fans()."""

    def test_fans_from_psutil(self):
        mock_fans = {
            "thinkpad": [Mock(label="fan1", current=2000)],
            "nct6775":  [Mock(label="",     current=1500)],
        }
        with patch('psutil.sensors_fans', return_value=mock_fans):
            from HeatSync import s_fans
            result = s_fans()
            assert isinstance(result, list)
            assert len(result) == 2
            for name, rpm in result:
                assert isinstance(name, str)
                assert isinstance(rpm, int)
                assert rpm > 0

    def test_fans_no_fans(self):
        with patch('psutil.sensors_fans', return_value={}):
            from HeatSync import s_fans
            result = s_fans()
            assert result == []

    def test_fans_psutil_exception(self):
        with patch('psutil.sensors_fans', side_effect=Exception("no fans")):
            from HeatSync import s_fans
            result = s_fans()
            assert isinstance(result, list)

    def test_fans_returns_list_of_tuples(self):
        mock_fans = {"cpu_fan": [Mock(label="CPU", current=1800)]}
        with patch('psutil.sensors_fans', return_value=mock_fans):
            from HeatSync import s_fans
            result = s_fans()
            assert all(len(item) == 2 for item in result)


class TestSettingsPersistence:
    """Tests for settings load/save functions."""

    def test_load_settings_returns_defaults_on_missing_file(self, tmp_path, monkeypatch):
        missing = str(tmp_path / "nonexistent.json")
        monkeypatch.setattr("heatsync.settings._SETTINGS_FILE", missing)
        from HeatSync import _load_settings, _DEFAULT_SETTINGS
        result = _load_settings()
        assert result["theme"] == _DEFAULT_SETTINGS["theme"]
        assert "gauges" in result

    def test_load_settings_merges_stored(self, tmp_path, monkeypatch):
        settings_path = str(tmp_path / "settings.json")
        import json
        with open(settings_path, "w") as f:
            json.dump({"theme": "light", "x": 100, "y": 200}, f)
        monkeypatch.setattr("heatsync.settings._SETTINGS_FILE", settings_path)
        from HeatSync import _load_settings
        result = _load_settings()
        assert result["theme"] == "light"
        assert result["x"] == 100
        assert "gauges" in result  # defaults filled in

    def test_save_settings_round_trip(self, tmp_path, monkeypatch):
        settings_path = str(tmp_path / "settings.json")
        monkeypatch.setattr("heatsync.settings._SETTINGS_FILE", settings_path)
        from HeatSync import _save_settings, _load_settings
        data = {"theme": "light", "compact": True, "x": 50, "y": 60}
        _save_settings(data)
        loaded = _load_settings()
        assert loaded["theme"] == "light"
        assert loaded["compact"] is True


class TestThemeSystem:
    """Tests for the theme system."""

    def test_dark_theme_attributes(self):
        from HeatSync import DARK_THEME
        assert DARK_THEME.name == "dark"
        assert DARK_THEME.bg.startswith("#")
        assert DARK_THEME.cyan.startswith("#")

    def test_light_theme_attributes(self):
        from HeatSync import LIGHT_THEME
        assert LIGHT_THEME.name == "light"
        assert LIGHT_THEME.bg != LIGHT_THEME.card_bg  # distinct colors

    def test_dark_light_themes_differ(self):
        from HeatSync import DARK_THEME, LIGHT_THEME
        assert DARK_THEME.bg != LIGHT_THEME.bg
        assert DARK_THEME.txt_hi != LIGHT_THEME.txt_hi
