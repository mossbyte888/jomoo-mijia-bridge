"""Connection strategy tests against HA APIs, without hardware access."""
import asyncio
import types
import unittest
from unittest.mock import AsyncMock, Mock
import test_coordinator as fixtures
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import UpdateFailed

class ConfigurableChecks(unittest.IsolatedAsyncioTestCase):
    coordinator = fixtures.CoordinatorChecks.coordinator
    async def test_on_demand_setting_disconnects_without_background_reconnect(self):
        c = self.coordinator()
        c.persistent = False
        c._ble_client = types.SimpleNamespace(is_connected=True, disconnect=AsyncMock())
        client = c._ble_client
        c.exchange = AsyncMock(return_value={"work_state": 0, "night_light": True})
        await c.set_setting("night_light", True)
        client.disconnect.assert_awaited_once()
        self.assertIsNone(c._ble_client)
        self.assertIsNone(c.update_interval)
        c.connection_failed(TimeoutError())
        c.async_request_refresh.assert_not_awaited()
        self.assertIsNone(c.update_interval)

    async def test_on_demand_refresh_and_action_disconnect_even_on_failure(self):
        for operation in ("refresh", "action"):
            c = self.coordinator()
            c.persistent = False
            client = types.SimpleNamespace(is_connected=True, disconnect=AsyncMock())
            c._ble_client = client
            c.exchange = AsyncMock(side_effect=TimeoutError())
            with self.assertRaises((HomeAssistantError, UpdateFailed)):
                await (c._async_update_data() if operation == "refresh" else c.perform_action("open_cover"))
            client.disconnect.assert_awaited_once()
            c.async_request_refresh.assert_not_awaited()

    async def test_cancel_closes_connection(self):
        c = self.coordinator()
        c.persistent = False
        client = types.SimpleNamespace(is_connected=True, disconnect=AsyncMock())
        c._ble_client = client
        started = asyncio.Event()
        async def exchange(*args):
            started.set()
            await asyncio.Event().wait()
        c.exchange = AsyncMock(side_effect=exchange)
        task = asyncio.create_task(c.set_setting("night_light", True))
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        client.disconnect.assert_awaited_once()
        self.assertFalse(c.operation_lock.locked())

    async def test_strategy_saved_and_release_does_not_reconnect_on_demand(self):
        c = self.coordinator()
        c.disconnect = AsyncMock()
        await c.set_persistent(False)
        self.assertFalse(c.config_entry.options['persistent_connection'])
        self.assertEqual(c.config_entry.options['other'], 'keep')
        c.disconnect.assert_awaited_once()
        await c.set_released(True)
        await c.set_released(False)
        c.async_refresh.assert_not_awaited()
        await c.set_persistent(True)
        self.assertTrue(c.config_entry.options['persistent_connection'])
        c.async_refresh.assert_awaited_once()

    async def test_strategy_switch_waits_for_mode_cleanup(self):
        c = self.coordinator()
        started, finish = asyncio.Event(), asyncio.Event()
        c.disconnect = AsyncMock()
        async def operation():
            async with c.operation():
                started.set()
                await finish.wait()
        mode = asyncio.create_task(operation())
        await started.wait()
        change = asyncio.create_task(c.set_persistent(False))
        await asyncio.sleep(0)
        c.disconnect.assert_not_awaited()
        finish.set()
        await asyncio.gather(mode, change)
        self.assertFalse(c.persistent)
        self.assertFalse(c.operation_lock.locked())

    async def test_controls_remain_callable_after_on_demand_failure(self):
        from jomoo_local.switch import JomooSwitch
        from jomoo_local.button import JomooButton
        c = self.coordinator()
        c.persistent = c.last_update_success = False
        c.model, c.address = 'sq9650', 'AA:BB:CC:DD:EE:01'
        c.config_entry.title = '测试设备'
        c.data = {}
        for entity in (JomooSwitch(c,'night_light','夜灯'),JomooButton(c,'open_cover','开盖')):
            self.assertTrue(entity.available)
            c.released = True
            self.assertFalse(entity.available)
            c.released = False

    async def test_startup_does_not_connect_when_on_demand(self):
        import jomoo_local
        from unittest.mock import patch
        for persistent in (False, True):
            c = types.SimpleNamespace(persistent=persistent, async_refresh=AsyncMock(), async_set_updated_data=Mock(), on_stop=Mock())
            entry = types.SimpleNamespace(async_on_unload=Mock())
            hass = types.SimpleNamespace(bus=types.SimpleNamespace(async_listen_once=Mock()),
                                         config_entries=types.SimpleNamespace(async_forward_entry_setups=AsyncMock()))
            with patch.object(jomoo_local, 'JomooCoordinator', return_value=c), patch.object(jomoo_local, 'PresetStore', return_value=types.SimpleNamespace(async_load=AsyncMock())):
                await jomoo_local.async_setup_entry(hass, entry)
            self.assertEqual(c.async_refresh.await_count, int(persistent))
            self.assertIs(entry.runtime_data, c)
