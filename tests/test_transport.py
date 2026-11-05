import asyncio
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch
from fixtures import core, capture, transport


class FakeClient:
    def __init__(self, drop_first=False, discard_write=False):
        self.drop_first = drop_first; self.discard_write = discard_write
        self.raw = bytearray(capture('sq9650')[0])
        self.writes = []; self.is_connected = True
        self.services = self

    async def __aenter__(self): return self
    async def __aexit__(self, *args): self.is_connected = False
    def get_characteristic(self, _):
        return types.SimpleNamespace(properties=['notify', 'write-without-response'])
    async def start_notify(self, _, callback): self.cb = callback
    async def stop_notify(self, _): pass
    async def write_gatt_char(self, _, frame, **kwargs):
        self.writes.append(frame)
        if frame == core.query('sq9650'):
            if self.drop_first:
                self.drop_first = False; return
            self.cb(None, self.raw[:8]); self.cb(None, self.raw[8:])
        elif not self.discard_write:
            self.raw[16] = (self.raw[16] & ~64) | (64 if frame[8] else 0)
            self.raw[1] = sum(self.raw[2:-1]) & 255


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def exchange(self, fake, key=None, value=None):
        bleak = types.SimpleNamespace(BleakClient=lambda *a, **kw: fake)
        device = types.SimpleNamespace(name='JOMOO_SMART_TEST_SQ')
        with patch.dict(sys.modules, {'bleak': bleak}), patch.object(transport, 'QUERY_RETRY_SECONDS', .005):
            return await transport.ToiletClient('sq9650', 'test').session(device, key, value)

    async def test_lost_first_query_is_retried_without_setting_write(self):
        fake=FakeClient(drop_first=True)
        state=await self.exchange(fake)
        self.assertFalse(state['night_light'])
        self.assertEqual(fake.writes, [core.query('sq9650')]*2)

    async def test_control_requires_readback(self):
        fake=FakeClient()
        state=await self.exchange(fake, 'night_light', True)
        self.assertTrue(state['night_light'])
        self.assertEqual(len(fake.writes), 3)

    async def test_same_value_does_not_write(self):
        fake=FakeClient()
        await self.exchange(fake, 'night_light', False)
        self.assertEqual(fake.writes, [core.query('sq9650')])

    async def test_fresh_mismatched_readback_keeps_state_and_does_not_retry_write(self):
        fake = FakeClient(discard_write=True)
        with patch.object(transport, 'READ_TIMEOUT_SECONDS', .025):
            with self.assertRaises(transport.CommandError) as caught:
                await self.exchange(fake, 'night_light', True)
        self.assertFalse(caught.exception.state['night_light'])
        self.assertEqual(len([f for f in fake.writes if f != core.query('sq9650')]), 1)

    async def test_seated_does_not_write(self):
        fake=FakeClient(); fake.raw[11] |= 128
        fake.raw[1] = sum(fake.raw[2:-1]) & 255
        with self.assertRaises(transport.CommandError) as caught:
            await self.exchange(fake, 'night_light', True)
        self.assertTrue(caught.exception.state['seated'])
        self.assertEqual(fake.writes, [core.query('sq9650')])

    async def test_foreign_device_name_rejected(self):
        with self.assertRaises(ValueError):
            await transport.ToiletClient('sq9650', 'test').session(types.SimpleNamespace(name='OTHER_VENDOR'))

    async def test_physical_write_is_not_retried_after_missing_feedback(self):
        fake = FakeClient(discard_write=True)
        bleak = types.SimpleNamespace(BleakClient=lambda *a, **kw: fake)
        with patch.dict(sys.modules, {'bleak': bleak}), patch.object(transport, 'QUERY_RETRY_SECONDS', .005), patch.object(transport, 'ACTION_TIMEOUT_SECONDS', .025):
            with self.assertRaisesRegex(TimeoutError, '指令已发送'):
                await transport.ToiletClient('sq9650', 'test').session(types.SimpleNamespace(name='JOMOO_SMART_TEST_SQ'), action='open_cover')
        commands = [f for f in fake.writes if f != core.query('sq9650')]
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0][6:8], bytes([0x33, 1]))

    async def test_already_closed_cover_does_not_send_motion(self):
        fake = FakeClient()
        bleak = types.SimpleNamespace(BleakClient=lambda *a, **kw: fake)
        with patch.dict(sys.modules, {'bleak': bleak}):
            await transport.ToiletClient('sq9650', 'test').session(types.SimpleNamespace(name='JOMOO_SMART_TEST_SQ'), action='close_cover')
        self.assertEqual(fake.writes, [core.query('sq9650')])

    async def test_missing_ea_prevents_new_setting_write(self):
        class ZsFake(FakeClient):
            async def write_gatt_char(self, _, frame, **kwargs):
                self.writes.append(frame)
                for raw in capture('zs800j'):
                    if raw[5] != 0xea:
                        self.cb(None, raw)
        fake = ZsFake()
        bleak = types.SimpleNamespace(BleakClient=lambda *a, **kw: fake)
        with patch.dict(sys.modules, {'bleak': bleak}), patch.object(transport, 'QUERY_RETRY_SECONDS', .005), patch.object(transport, 'READ_TIMEOUT_SECONDS', .025):
            with self.assertRaises(TimeoutError):
                await transport.ToiletClient('zs800j','test').session(types.SimpleNamespace(name='JOMOO_SMART_TEST_ZS'), 'cover_sensitivity', 1)
        self.assertTrue(all(f == core.query('zs800j') for f in fake.writes))

    async def test_missing_ea_still_reports_other_read_only_entities(self):
        class ZsFake(FakeClient):
            async def write_gatt_char(self, _, frame, **kwargs):
                self.writes.append(frame)
                for raw in capture('zs800j'):
                    if raw[5] != 0xea:
                        self.cb(None, raw)
        fake = ZsFake()
        bleak = types.SimpleNamespace(BleakClient=lambda *a, **kw: fake)
        with patch.dict(sys.modules, {'bleak': bleak}), patch.object(transport, 'QUERY_RETRY_SECONDS', .005):
            result = await transport.ToiletClient('zs800j','test').session(types.SimpleNamespace(name='JOMOO_SMART_TEST_ZS'))
        self.assertEqual(result['water_temp_level'], 0)
        self.assertNotIn('cover_sensitivity', result)

    async def test_injected_connector_is_used_and_closed(self):
        fake = FakeClient()
        factory = lambda device: fake
        with patch.dict(sys.modules, {'bleak': types.SimpleNamespace(BleakClient=lambda *a, **kw: self.fail('raw connector used'))}):
            result = await transport.ToiletClient('sq9650','test',factory).session(types.SimpleNamespace(name='JOMOO_SMART_TEST_SQ'))
        self.assertFalse(result['night_light'])
        self.assertFalse(fake.is_connected)
