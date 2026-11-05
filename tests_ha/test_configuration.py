"""Checks against real HA APIs; no Bluetooth adapter or live account needed."""
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'custom_components'))
import jomoo_local
from jomoo_local.config_flow import JomooFlow
from jomoo_local.switch import JomooSwitch
from homeassistant.data_entry_flow import AbortFlow


class ConfigurationChecks(unittest.IsolatedAsyncioTestCase):
    async def test_address_validation_and_entry_contents(self):
        flow=JomooFlow()
        flow.async_set_unique_id=AsyncMock()
        flow._abort_if_unique_id_configured=Mock()
        bad=await flow.async_step_user({'model':'sq9650','address':'bad'})
        self.assertEqual(bad['errors'],{'address':'invalid_address'})
        flow.async_set_unique_id.assert_not_called()
        good=await flow.async_step_user({'model':'sq9650','address':'aa-bb-cc-dd-ee-01','name':' 测试设备 '})
        self.assertEqual(good['data'],{'model':'sq9650','address':'AA:BB:CC:DD:EE:01'})
        self.assertEqual(good['title'],'测试设备')
        flow.async_set_unique_id.assert_awaited_once_with('AA:BB:CC:DD:EE:01')

    async def test_duplicate_address_aborts(self):
        flow=JomooFlow()
        flow.async_set_unique_id=AsyncMock()
        flow._abort_if_unique_id_configured=Mock(side_effect=AbortFlow('already_configured'))
        with self.assertRaises(AbortFlow):
            await flow.async_step_user({'model':'zs800j','address':'AA:BB:CC:DD:EE:01'})

    async def test_unload_closes_link_only_after_success(self):
        entry=types.SimpleNamespace(runtime_data=types.SimpleNamespace(async_shutdown=AsyncMock()))
        hass=types.SimpleNamespace(config_entries=types.SimpleNamespace(async_unload_platforms=AsyncMock(return_value=False)))
        self.assertFalse(await jomoo_local.async_unload_entry(hass,entry))
        entry.runtime_data.async_shutdown.assert_not_called()
        hass.config_entries.async_unload_platforms.return_value=True
        self.assertTrue(await jomoo_local.async_unload_entry(hass,entry))
        entry.runtime_data.async_shutdown.assert_awaited_once()

    async def test_same_model_entities_have_separate_ids(self):
        def coordinator(address):
            return types.SimpleNamespace(model='sq9650',address=address,config_entry=types.SimpleNamespace(title='测试'),
                                         released=False,last_update_success=True,data={'night_light':False})
        a=JomooSwitch(coordinator('AA:BB:CC:DD:EE:01'),'night_light','夜灯')
        b=JomooSwitch(coordinator('AA:BB:CC:DD:EE:02'),'night_light','夜灯')
        self.assertNotEqual(a.entity_id,b.entity_id)
        self.assertNotEqual(a.unique_id,b.unique_id)
        self.assertEqual(a.entity_id,'switch.jomoo_sq9650_aabbccddee01_night_light')
        self.assertTrue(a.available)

    async def test_automation_schema_and_event_guards(self):
        from datetime import datetime, timedelta, UTC
        from homeassistant.components.automation.config import PLATFORM_SCHEMA
        from homeassistant.core import HomeAssistant, State
        from homeassistant.helpers.template import Template
        auto=json.loads((ROOT/'examples/automation.yaml').read_text())
        hass=HomeAssistant('/tmp/jomoo-isolated-config')
        PLATFORM_SCHEMA(auto)
        guard=Template(auto['conditions'][0]['value_template'],hass)
        routes=auto['variables']['routes']
        name='jomoo_sq9650_night_light_on'
        now=datetime.now(UTC)
        def check(old,new,event_name=name):
            trigger=types.SimpleNamespace(from_state=old,to_state=new)
            return guard.async_render({'trigger':trigger,'routes':routes,'event_name':event_name})
        before=State('event.example',(now-timedelta(seconds=5)).isoformat())
        fresh=State('event.example',now.isoformat(),{'事件名称':name})
        self.assertTrue(check(before,fresh))
        self.assertFalse(check(None,fresh))
        self.assertFalse(check(State('event.example','unavailable'),fresh))
        self.assertFalse(check(fresh,fresh))
        self.assertFalse(check(before,State('event.example',(now-timedelta(seconds=40)).isoformat())))
        self.assertFalse(check(before,fresh,'unlisted_event'))
        self.assertFalse(check(before,None))
