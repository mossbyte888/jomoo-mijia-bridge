"""Candidate tests inside HA; no live device writes."""
import asyncio
from contextlib import asynccontextmanager
import sys
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'custom_components'))
from jomoo_local import JomooCoordinator, BluetoothReleased
from jomoo_local.scheduling import OperationQueue
from jomoo_local.transport import CommandError, SettingNotApplied
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import UpdateFailed


class CoordinatorChecks(unittest.IsolatedAsyncioTestCase):
    def coordinator(self):
        c = object.__new__(JomooCoordinator)
        c.model, c.address = 'sq9650', 'test'
        c.released = c.stopping = False
        c._ble_client = c._device = c._last_setting = None
        c._release_lock = asyncio.Lock()
        c.queue = OperationQueue()
        c.data = {'work_state': 0, 'night_light': False}
        c.async_set_updated_data = Mock()
        c.async_update_listeners = Mock()
        c.async_set_update_error = Mock()
        c.async_request_refresh = AsyncMock()
        c.async_refresh = AsyncMock()
        c.config_entry = types.SimpleNamespace(options={'other': 'keep'})
        def update_entry(entry, options): entry.options = options
        c.hass = types.SimpleNamespace(async_create_task=lambda coro: coro.close(), config_entries=types.SimpleNamespace(async_update_entry=Mock(side_effect=update_entry)))
        return c

    async def test_validation_rejection_keeps_fresh_state_available(self):
        c = self.coordinator()
        fresh = {'work_state': 0, 'light_sensor': True}
        c.exchange = AsyncMock(side_effect=CommandError('光感夜灯已开启', fresh))
        with self.assertRaises(HomeAssistantError): await c.set_setting('night_light', True)
        c.async_set_updated_data.assert_called_once_with(fresh)
        c.async_set_update_error.assert_not_called()

    async def test_timeout_marks_unavailable_and_requests_recovery(self):
        c = self.coordinator()
        c.exchange = AsyncMock(side_effect=TimeoutError())
        with self.assertRaisesRegex(HomeAssistantError, 'TimeoutError'): await c.set_setting('night_light', True)
        c.async_set_update_error.assert_called_once()
        self.assertEqual(c.update_interval.total_seconds(), 10)
        c.async_request_refresh.assert_called_once()

    async def test_poll_timeout_recovers_on_short_interval(self):
        c = self.coordinator()
        c.exchange = AsyncMock(side_effect=TimeoutError())
        with self.assertRaisesRegex(UpdateFailed, 'TimeoutError'): await c._async_update_data()
        self.assertEqual(c.update_interval.total_seconds(), 10)

    async def test_success_restores_normal_polling(self):
        c = self.coordinator()
        c.exchange = AsyncMock(return_value={'work_state': 0})
        self.assertEqual(await c._async_update_data(), {'work_state': 0})
        self.assertEqual(c.update_interval.total_seconds(), 30)

    async def test_two_sessions_reuse_connection_and_explicit_release_disconnects(self):
        c = self.coordinator()
        client = types.SimpleNamespace(is_connected=True, disconnect=AsyncMock())
        connect = AsyncMock(return_value=client)
        with patch('bleak_retry_connector.establish_connection', connect):
            async with c.connection(Mock()) as first: self.assertIs(first, client)
            async with c.connection(Mock()) as second: self.assertIs(second, client)
            connect.assert_awaited_once()
            client.disconnect.assert_not_called()
            await c.set_released(True)
        client.disconnect.assert_awaited_once()
        self.assertEqual(c.config_entry.options, {'other': 'keep', 'bluetooth_released': True})
        self.assertIsNone(c.update_interval)

    async def test_release_suppresses_poll_control_and_reconnect(self):
        c = self.coordinator()
        await c.set_released(True)
        c.client = types.SimpleNamespace(session=AsyncMock())
        await c._async_update_data()
        with self.assertRaises(BluetoothReleased): await c.set_setting('night_light', True)
        with self.assertRaises(BluetoothReleased): await c.perform_action('open_cover')
        c.client.session.assert_not_called()
        c.connection_failed(TimeoutError())
        c.async_request_refresh.assert_not_called()
        self.assertIsNone(c.update_interval)
        await c.set_released(False)
        self.assertFalse(c.config_entry.options['bluetooth_released'])
        c.async_refresh.assert_awaited_once()

    async def test_duplicate_settings_share_one_exchange(self):
        c = self.coordinator()
        started, finish = asyncio.Event(), asyncio.Event()
        async def exchange(*a):
            started.set(); await finish.wait(); return c.data
        c.exchange = AsyncMock(side_effect=exchange)
        first = asyncio.create_task(c.set_setting('night_light', True))
        await started.wait()
        second = asyncio.create_task(c.set_setting('night_light', True))
        await asyncio.sleep(0)
        finish.set()
        await asyncio.gather(first, second)
        c.exchange.assert_awaited_once()

    async def test_opposite_setting_is_a_barrier_to_coalescing(self):
        c = self.coordinator()
        finish = asyncio.Event()
        async def exchange(*a): await finish.wait(); return c.data
        c.exchange = AsyncMock(side_effect=exchange)
        tasks = []
        for value in [True, False, True]:
            tasks.append(asyncio.create_task(c.set_setting('night_light', value)))
            await asyncio.sleep(0)
        finish.set(); await asyncio.gather(*tasks)
        self.assertEqual([call.args for call in c.exchange.await_args_list], [('night_light', True), ('night_light', False), ('night_light', True)])

    async def test_release_blocks_commands_already_waiting(self):
        c = self.coordinator()
        c.client = types.SimpleNamespace(session=AsyncMock())
        async with c.queue.slot():
            command = asyncio.create_task(c.perform_action('open_cover'))
            await asyncio.sleep(0)
            release = asyncio.create_task(c.set_released(True))
            await asyncio.sleep(0)
        await release
        with self.assertRaises(BluetoothReleased): await command
        c.client.session.assert_not_called()

    async def test_io_error_drops_link_but_rejected_setting_keeps_it(self):
        c = self.coordinator()
        client = types.SimpleNamespace(is_connected=True, disconnect=AsyncMock())
        c._ble_client = client
        with self.assertRaises(CommandError):
            async with c.connection(Mock()): raise CommandError('reject', c.data)
        client.disconnect.assert_not_called()
        with self.assertRaises(TimeoutError):
            async with c.connection(Mock()): raise TimeoutError()
        client.disconnect.assert_awaited_once()
        self.assertIsNone(c._ble_client)

    async def test_connected_session_does_not_need_advertisement(self):
        c = self.coordinator()
        c._ble_client = types.SimpleNamespace(is_connected=True)
        c._device = object()
        c.client = types.SimpleNamespace(session=AsyncMock(return_value=c.data))
        with patch('jomoo_local.async_ble_device_from_address', side_effect=AssertionError('must not scan')):
            await c.exchange('night_light', False)
        c.client.session.assert_awaited_once_with(c._device, 'night_light', False, None)


    async def test_explicit_unapplied_absolute_setting_reconnects_once(self):
        c = self.coordinator()
        c._ble_client = types.SimpleNamespace(is_connected=True)
        c._device = object()
        c.disconnect = AsyncMock()
        state = {'work_state': 0, 'night_light': True}
        c.client = types.SimpleNamespace(session=AsyncMock(side_effect=[SettingNotApplied('not applied', c.data), state]))
        self.assertEqual(await c.exchange('night_light', True), state)
        self.assertEqual(c.client.session.await_count, 2)
        c.disconnect.assert_awaited_once()

    async def test_no_replay_on_timeout_toggle_or_repeated_rejection(self):
        for key, errors, count in [
            ('night_light', [TimeoutError()], 1),
            ('auto_temp', [SettingNotApplied('not applied', {})], 1),
            ('night_light', [SettingNotApplied('not applied', {}), SettingNotApplied('still not applied', {})], 2),
        ]:
            c = self.coordinator()
            c._ble_client = types.SimpleNamespace(is_connected=True)
            c._device = object()
            c.disconnect = AsyncMock()
            c.client = types.SimpleNamespace(session=AsyncMock(side_effect=errors))
            with self.assertRaises((TimeoutError, SettingNotApplied)):
                await c.exchange(key, True)
            self.assertEqual(c.client.session.await_count, count)


if __name__ == '__main__':
    unittest.main()
