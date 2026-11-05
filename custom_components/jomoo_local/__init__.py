"""Home Assistant adapter with persistent, independently released BLE links."""
import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
import logging
from time import monotonic

from homeassistant.components.bluetooth import async_ble_device_from_address
from homeassistant.const import Platform, EVENT_HOMEASSISTANT_STOP
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from .core import PROFILES
from .transport import ToiletClient, CommandError, SettingNotApplied
from .operations import working_label
from .scheduling import OperationQueue

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SWITCH, Platform.SELECT, Platform.BUTTON, Platform.SENSOR]


class BluetoothReleased(HomeAssistantError):
    """User released this toilet to the phone; never reconnect implicitly."""


class JomooCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry):
        super().__init__(hass, _LOGGER, name=entry.title, config_entry=entry, update_interval=timedelta(seconds=30))
        self.model = entry.data["model"]
        self.address = entry.data["address"]
        self.client = ToiletClient(self.model, self.address, self.connection)
        self.queue = OperationQueue()
        self.released = bool(entry.options.get("bluetooth_released", False))
        self.stopping = False
        self._ble_client = None
        self._device = None
        self._last_setting = None
        self._release_lock = asyncio.Lock()
        if self.released:
            self.update_interval = None

    async def disconnect(self):
        client, self._ble_client = self._ble_client, None
        if client is not None:
            try:
                await client.disconnect()
            except BaseException:
                if client.is_connected:
                    self._ble_client = client
                raise

    def disconnected(self, client):
        # Intentional disconnect clears the reference before invoking BlueZ.
        if client is self._ble_client:
            self._ble_client = None
            if not self.released and not self.stopping:
                self.connection_failed(ConnectionError("蓝牙连接已断开"))

    @asynccontextmanager
    async def connection(self, device):
        from bleak import BleakClient
        from bleak_retry_connector import establish_connection
        if self._ble_client is None or not self._ble_client.is_connected:
            started = monotonic()
            self._ble_client = await establish_connection(
                BleakClient, device, PROFILES[self.model]["name"], max_attempts=2,
                disconnected_callback=self.disconnected,
                ble_device_callback=lambda: async_ble_device_from_address(self.hass, self.address, connectable=True) or device,
            )
            _LOGGER.info("%s BLE connected in %.2fs", self.model, monotonic() - started)
        try:
            yield self._ble_client
        except CommandError:
            # A device-side setting rejection is not a broken connection.
            raise
        except BaseException:
            await self.disconnect()
            raise

    def normal_interval(self, state):
        if self.released or self.stopping:
            return None
        return timedelta(seconds=5 if working_label(self.model, state) not in ("就绪", "待机") else 30)

    def accept_state(self, state):
        self.update_interval = self.normal_interval(state)
        self.async_set_updated_data(state)

    def connection_failed(self, exc):
        self.update_interval = None if self.released or self.stopping else timedelta(seconds=10)
        self.async_set_update_error(UpdateFailed(str(exc) or type(exc).__name__))
        if not self.released and not self.stopping:
            self.hass.async_create_task(self.async_request_refresh())

    async def exchange(self, key=None, value=None, action=None):
        control = key is not None or action is not None
        started = monotonic()
        async with self.queue.slot(1 if control else 2):
            waited = monotonic() - started
            if self.released or self.stopping:
                raise BluetoothReleased("已释放蓝牙给小程序；请先关闭“释放蓝牙”开关")
            # Connected toilets stop advertising. Reuse their original BLEDevice.
            if self._ble_client is None or not self._ble_client.is_connected:
                self._device = async_ble_device_from_address(self.hass, self.address, connectable=True)
                if self._device is None:
                    from bleak import BleakScanner
                    self._device = await BleakScanner.find_device_by_address(self.address, timeout=8)
            try:
                result = await self.client.session(self._device, key, value, action)
            except SettingNotApplied as exc:
                # Only absolute setters with explicit contrary readback can be
                # retried. Keep our queue slot so a newer target cannot overtake
                # this one. The new session reads again before any write.
                if key is None or key == "auto_temp" or self.released or self.stopping:
                    raise
                self.accept_state(exc.state)
                _LOGGER.warning("%s %s not applied; reconnecting once with fresh readback", self.model, key)
                await self.disconnect()
                if self.released or self.stopping:
                    raise BluetoothReleased("已释放蓝牙给小程序；请先关闭“释放蓝牙”开关")
                result = await self.client.session(self._device, key, value, action)
            if control:
                _LOGGER.info("%s %s=%s confirmed in %.2fs (queue %.2fs)", self.model, key or action, value, monotonic() - started, waited)
            return result

    async def _async_update_data(self):
        if self.released or self.stopping:
            self.update_interval = None
            return self.data or {}
        try:
            state = await self.exchange()
            self.update_interval = self.normal_interval(state)
            return state
        except BluetoothReleased:
            self.update_interval = None
            return self.data or {}
        except Exception as exc:
            self.update_interval = None if self.released or self.stopping else timedelta(seconds=10)
            raise UpdateFailed(f"蓝牙状态读取失败：{str(exc) or type(exc).__name__}") from exc

    async def set_setting(self, key, value):
        if self.released or self.stopping:
            raise BluetoothReleased("已释放蓝牙给小程序；请先关闭“释放蓝牙”开关")
        previous = self._last_setting
        # Only adjacent identical requests share work. on/off/on retains order.
        if previous is not None and previous[:2] == (key, value) and not previous[2].done():
            await asyncio.shield(previous[2])
            return
        result = asyncio.get_running_loop().create_future()
        result.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        self._last_setting = (key, value, result)
        try:
            await self._set_setting(key, value)
        except asyncio.CancelledError:
            result.cancel()
            raise
        except Exception as exc:
            result.set_exception(exc)
            raise
        else:
            result.set_result(None)

    async def _set_setting(self, key, value):
        try:
            state = await self.exchange(key, value)
        except BluetoothReleased:
            raise
        except CommandError as exc:
            self.accept_state(exc.state)
            raise HomeAssistantError(str(exc)) from exc
        except Exception as exc:
            self.connection_failed(exc)
            raise HomeAssistantError(f"未确认设置成功：{str(exc) or type(exc).__name__}") from exc
        self.accept_state(state)

    async def perform_action(self, action):
        self._last_setting = None
        try:
            state = await self.exchange(action=action)
        except BluetoothReleased:
            raise
        except CommandError as exc:
            self.accept_state(exc.state)
            raise HomeAssistantError(str(exc)) from exc
        except Exception as exc:
            self.connection_failed(exc)
            raise HomeAssistantError(str(exc) or type(exc).__name__) from exc
        self.accept_state(state)

    async def set_released(self, released):
        async with self._release_lock:
            self._last_setting = None
            self.released = released
            self.hass.config_entries.async_update_entry(
                self.config_entry, options={**self.config_entry.options, "bluetooth_released": released}
            )
            if released:
                self.update_interval = None
                # Do not interrupt an already-sent physical action. Reject all
                # queued commands, and disconnect before reporting release done.
                async with self.queue.slot(0):
                    await self.disconnect()
                self.async_set_updated_data(self.data or {})
            else:
                self.update_interval = timedelta(seconds=10)
                await self.async_refresh()
            self.async_update_listeners()

    async def on_stop(self, event):
        await self.async_shutdown()

    async def async_shutdown(self):
        if self.stopping:
            return
        self.stopping = True
        await super().async_shutdown()
        async with self.queue.slot(0):
            await self.disconnect()


async def async_setup_entry(hass, entry):
    coordinator = JomooCoordinator(hass, entry)
    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, coordinator.on_stop))
    # Keep the release switch accessible even if the phone currently owns BLE.
    await coordinator.async_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass, entry):
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_shutdown()
    return unloaded
