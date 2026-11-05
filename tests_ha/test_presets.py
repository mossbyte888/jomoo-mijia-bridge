"""Run in an isolated HA Python environment; never connect to real devices."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "custom_components"))
from jomoo_local.presets import PresetStore
from jomoo_local.select import PresetSelect
from jomoo_local.presets import async_apply
from jomoo_local.preset_config import defaults, KEEP
from jomoo_local import BluetoothReleased, JomooCoordinator
from homeassistant.core import HomeAssistant, Context
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.script import Script, async_validate_actions_config
from homeassistant.components.script.config import SCRIPT_ENTITY_SCHEMA



class EditablePresetChecks(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.hass = HomeAssistant(self.directory.name)
        self.entry = SimpleNamespace(entry_id="test_entry", data={"model": "zs800j"})
        self.manager = PresetStore(self.hass, self.entry)

    async def asyncTearDown(self):
        await self.hass.async_block_till_done()
        self.directory.cleanup()

    async def test_initial_values_and_saved_values_survive_new_instance(self):
        await self.manager.async_load()
        self.assertEqual(self.manager.data, defaults("zs800j"))
        await self.manager.async_set("eco", "seat_temp_level", "标准")
        fresh = PresetStore(self.hass, self.entry)
        await fresh.async_load()
        self.assertEqual(fresh.data["eco"]["seat_temp_level"], "标准")
        self.assertEqual(fresh.data["default"], defaults("zs800j")["default"])

    async def test_corrupt_storage_does_not_silently_reset(self):
        self.manager.store.async_load = AsyncMock(return_value={"eco": {}})
        self.manager.store.async_save = AsyncMock()
        with self.assertRaises(HomeAssistantError):
            await self.manager.async_load()
        self.manager.store.async_save.assert_not_awaited()

    async def test_failed_save_does_not_publish_unsaved_value(self):
        await self.manager.async_load()
        before = deepcopy(self.manager.data)
        self.manager.store.async_save = AsyncMock(side_effect=OSError("disk full"))
        with self.assertRaises(HomeAssistantError):
            await self.manager.async_set("eco", "seat_temp_level", "标准")
        self.assertEqual(self.manager.data, before)

    async def test_invalid_value_is_rejected(self):
        await self.manager.async_load()
        self.manager.store.async_save = AsyncMock()
        with self.assertRaises(HomeAssistantError):
            await self.manager.async_set("eco", "seat_temp_level", "100度")
        self.manager.store.async_save.assert_not_awaited()

    async def test_silent_store_write_failure_is_reported(self):
        await self.manager.async_load()
        before = deepcopy(self.manager.data)
        self.manager.store.async_save = AsyncMock()
        with self.assertRaises(HomeAssistantError):
            await self.manager.async_set("eco", "seat_temp_level", "标准")
        self.assertEqual(self.manager.data, before)

    async def test_concurrent_edits_preserve_both_values(self):
        await self.manager.async_load()
        await asyncio.gather(self.manager.async_set("eco", "seat_temp_level", "标准"),
                             self.manager.async_set("default", "water_temp_level", "偏低"))
        fresh = PresetStore(self.hass, self.entry)
        await fresh.async_load()
        self.assertEqual(fresh.data["eco"]["seat_temp_level"], "标准")
        self.assertEqual(fresh.data["default"]["water_temp_level"], "偏低")

    async def test_editor_entities_work_offline_without_ble(self):
        await self.manager.async_load()
        coordinator = SimpleNamespace(model="zs800j", address="AA:BB:CC:DD:EE:01", released=True, last_update_success=False,
                                      presets=self.manager, set_setting=AsyncMock())
        select = PresetSelect(coordinator, "eco", "seat_temp_level")
        switch = PresetSelect(coordinator, "default", "uv_water")
        for entity in (select, switch):
            entity.async_write_ha_state = Mock()
            self.assertTrue(entity.available)
        await select.async_select_option("标准")
        await switch.async_select_option("关闭")
        self.assertEqual(select.current_option, "标准")
        self.assertEqual(switch.current_option, "关闭")
        coordinator.set_setting.assert_not_awaited()


    async def test_same_model_storage_and_entity_ids_are_distinct(self):
        await self.manager.async_load()
        other = PresetStore(self.hass, SimpleNamespace(entry_id="other", data={"model": "zs800j"}))
        await other.async_load()
        await self.manager.async_set("default", "seat_temp_level", "标准")
        self.assertEqual(other.data["default"]["seat_temp_level"], KEEP)
        entities = [PresetSelect(SimpleNamespace(model="zs800j", address=address, presets=self.manager), "eco", "seat_temp_level")
                    for address in ("AA:BB:CC:DD:EE:01", "AA:BB:CC:DD:EE:02")]
        self.assertNotEqual(entities[0].unique_id, entities[1].unique_id)
        self.assertNotEqual(entities[0].entity_id, entities[1].entity_id)


class ApplyChecks(unittest.IsolatedAsyncioTestCase):
    def coordinator(self, model="zs800j"):
        state = {"seat_temp_level": 3, "water_temp_level": 3, "air_temp": 3, "auto_temp": True,
                 "prewetting": True, "auto_bubble": False, "light_sensor": True, "night_light": True,
                 "work_state": 1 if model == "zs800j" else 0, "seated": False, "bubble_running": False,
                 "auto_running": False, "flush_running": False, "unblock_running": False, "temperature_fault": False}
        c = SimpleNamespace(model=model, presets=SimpleNamespace(data=defaults(model)), data=state,
                            operation_lock=asyncio.Lock(), persistent=True, released=False, stopping=False, connection_failed=Mock())
        async def exchange():
            if c.released or c.stopping:
                raise BluetoothReleased("已释放蓝牙")
            return deepcopy(c.data)
        def accept(state): c.data = state
        async def write(key, value):
            if c.released or c.stopping:
                raise BluetoothReleased("已释放蓝牙")
            c.data[key] = value
            if key == "prewetting": c.data["auto_bubble"] = value
        c.operation = JomooCoordinator.operation.__get__(c)
        c.queue = __import__("jomoo_local.scheduling", fromlist=["OperationQueue"]).OperationQueue()
        c.disconnect = AsyncMock()
        c.async_update_listeners = Mock()
        c.exchange = AsyncMock(side_effect=exchange)
        c.accept_state = Mock(side_effect=accept)
        c._set_setting = AsyncMock(side_effect=write)
        return c

    async def test_default_noop_and_eco_temperatures(self):
        c = self.coordinator()
        await async_apply(c, "default")
        c._set_setting.assert_not_awaited()
        await async_apply(c, "eco")
        self.assertEqual(c._set_setting.await_args_list[0].args, ("auto_temp", False))
        for key in ("seat_temp_level", "water_temp_level", "air_temp"):
            self.assertEqual(c.data[key], 0)
        count = c._set_setting.await_count
        await async_apply(c, "eco")
        self.assertEqual(c._set_setting.await_count, count)

    async def test_edit_during_run_applies_next_time_only(self):
        c = self.coordinator()
        write = c._set_setting.side_effect
        async def mutate(key, value):
            c.presets.data["eco"]["seat_temp_level"] = "最高"
            await write(key, value)
        c._set_setting.side_effect = mutate
        await async_apply(c, "eco")
        self.assertEqual(c.data["seat_temp_level"], 0)
        await async_apply(c, "eco")
        self.assertEqual(c.data["seat_temp_level"], 5)

    async def test_preflight_conflict_missing_state_busy_and_release(self):
        for failure in ("conflict", "missing", "busy", "released", "stopping"):
            c = self.coordinator()
            if failure == "conflict":
                c.presets.data["eco"].update(prewetting="关闭", auto_bubble="开启")
            elif failure == "missing": del c.data["water_temp_level"]
            elif failure == "busy": c.data["seated"] = True
            else: setattr(c, failure, True)
            with self.assertRaises(HomeAssistantError): await async_apply(c, "eco")
            c._set_setting.assert_not_awaited()

    async def test_sensor_wetting_and_foam_ordering(self):
        sq = self.coordinator("sq9650")
        sq.presets.data["default"].update(night_light="关闭", light_sensor="开启")
        await async_apply(sq, "default")
        sq._set_setting.assert_not_awaited()
        sq.presets.data["default"]["light_sensor"] = "关闭"
        await async_apply(sq, "default")
        self.assertEqual([call.args[0] for call in sq._set_setting.await_args_list], ["light_sensor", "night_light"])
        zs = self.coordinator()
        zs.data["prewetting"] = False
        zs.presets.data["default"]["prewetting"] = "开启"
        await async_apply(zs, "default")
        self.assertEqual([call.args for call in zs._set_setting.await_args_list], [("prewetting", True), ("auto_bubble", False)])
        zs.presets.data["default"].update(prewetting="关闭", auto_bubble=KEEP)
        await async_apply(zs, "default")
        self.assertFalse(zs.data["auto_bubble"])

    async def test_readback_mismatch_is_not_success_and_write_error_stops(self):
        c = self.coordinator()
        c._set_setting = AsyncMock()  # simulated write acknowledged but state unchanged
        with self.assertRaisesRegex(HomeAssistantError, "模式未全部生效"):
            await async_apply(c, "eco")
        c._set_setting = AsyncMock(side_effect=HomeAssistantError("未确认设置成功"))
        with self.assertRaises(HomeAssistantError): await async_apply(c, "eco")
        self.assertEqual(c._set_setting.await_count, 1)

    async def test_release_mid_run_stops_remaining_writes(self):
        c = self.coordinator()
        write = c._set_setting.side_effect
        async def release(key, value):
            await write(key, value)
            c.released = True
        c._set_setting.side_effect = release
        with self.assertRaises(BluetoothReleased): await async_apply(c, "eco")
        self.assertEqual(c.data["seat_temp_level"], 3)

    async def test_modes_are_serialized_with_independent_snapshots(self):
        c = self.coordinator()
        c.presets.data["default"]["seat_temp_level"] = "偏低"
        started, finish = asyncio.Event(), asyncio.Event()
        write = c._set_setting.side_effect
        async def block(key, value):
            started.set()
            await finish.wait()
            await write(key, value)
        c._set_setting.side_effect = block
        eco = asyncio.create_task(async_apply(c, "eco"))
        await started.wait()
        normal = asyncio.create_task(async_apply(c, "default"))
        await asyncio.sleep(0)
        finish.set()
        await asyncio.gather(eco, normal)
        self.assertEqual(c.data["seat_temp_level"], 2)
        self.assertEqual(c._set_setting.await_args_list[-1].args, ("seat_temp_level", 2))

    async def test_disconnect_is_reported(self):
        c = self.coordinator()
        c.exchange = AsyncMock(side_effect=TimeoutError())
        with self.assertRaisesRegex(HomeAssistantError, "模式执行中断"):
            await async_apply(c, "eco")
        c.connection_failed.assert_called_once()
        c._set_setting.assert_not_awaited()

    async def test_on_demand_mode_disconnects_once_after_whole_preset(self):
        c = self.coordinator()
        c.persistent = False
        original = c._set_setting.side_effect
        async def write(key, value):
            c.disconnect.assert_not_awaited()
            await original(key, value)
        c._set_setting.side_effect = write
        await async_apply(c, 'eco')
        self.assertGreater(c._set_setting.await_count, 1)
        c.disconnect.assert_awaited_once()

    async def test_on_demand_failed_preset_disconnects(self):
        c = self.coordinator()
        c.persistent = False
        c._set_setting = AsyncMock(side_effect=HomeAssistantError('failed'))
        with self.assertRaises(HomeAssistantError):
            await async_apply(c, 'eco')
        c.disconnect.assert_awaited_once()
