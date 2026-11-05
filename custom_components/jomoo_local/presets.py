"""Editable local presets. Editing these entities never sends BLE commands."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import Entity, EntityCategory
from homeassistant.helpers.storage import Store

from .const import DOMAIN

from .preset_config import MODES, defaults, validate as validate_config, plan
from .identity import entity_prefix
from .core import require_idle


def validate(model, data):
    try:
        validate_config(model, data)
    except ValueError as exc:
        raise HomeAssistantError(str(exc)) from exc


class PresetStore:
    def __init__(self, hass, entry):
        self.hass = hass
        self.model = entry.data["model"]
        self.store = Store(hass, 1, f"{DOMAIN}.presets_{entry.entry_id}")
        self.lock = asyncio.Lock()
        self.data = None

    async def async_load(self):
        data = await self.store.async_load()
        if data is None:
            data = defaults(self.model)
            validate(self.model, data)
            await self.async_save_checked(data)
        validate(self.model, data)
        self.data = data

    async def async_save_checked(self, data):
        # HA Store logs some disk-write errors instead of raising them. Verify
        # the actual file before reporting success to a configuration entity.
        try:
            await self.store.async_save(data)
            def read_saved():
                return json.loads(Path(self.store.path).read_text())["data"]
            saved = await self.hass.async_add_executor_job(read_saved)
            if saved != data:
                raise HomeAssistantError("模式配置未写入磁盘，请检查主机存储空间后重试")
        except (OSError, ValueError, KeyError) as exc:
            raise HomeAssistantError("模式保存失败，请检查主机存储空间") from exc

    async def async_set(self, mode, key, value):
        async with self.lock:
            if mode not in MODES or key not in self.data[mode]:
                raise HomeAssistantError("不支持的模式设置")
            candidate = deepcopy(self.data)
            candidate[mode][key] = value
            validate(self.model, candidate)
            # Publish only after the new value has been saved successfully.
            await self.async_save_checked(candidate)
            self.data = candidate


class PresetEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, mode, key, name, domain):
        self.presets = coordinator.presets
        self.mode = mode
        self.key = key
        self._attr_name = f"{MODES[mode]} · {name}"
        self._attr_unique_id = f"{coordinator.address}_preset_{mode}_{key}"
        self.entity_id = f"{domain}.{entity_prefix(coordinator.model, coordinator.address)}_preset_{mode}_{key}"
        self._attr_device_info = {"identifiers": {(DOMAIN, coordinator.address)}}
        self._attr_extra_state_attributes = {"preset": mode, "setting": key, "configuration_only": True}

    async def async_save(self, value):
        await self.presets.async_set(self.mode, self.key, value)
        self.async_write_ha_state()


async def async_apply(coordinator, mode):
    """Snapshot saved targets at invocation and serialize this device's controls."""
    if mode not in MODES:
        raise HomeAssistantError("不支持的模式")
    values = deepcopy(coordinator.presets.data[mode])
    async with coordinator.control_lock:
        try:
            state = await coordinator.exchange()
            coordinator.accept_state(state)
            target = plan(coordinator.model, values, state)
            if not target:
                return
            require_idle(coordinator.model, state)
            for key, value in target.items():
                if (coordinator.data or {}).get(key) != value:
                    await coordinator._set_setting(key, value)
            state = await coordinator.exchange()
            coordinator.accept_state(state)
            failed = [key for key, value in target.items() if state.get(key) != value]
            if failed:
                raise HomeAssistantError("模式未全部生效：" + ", ".join(failed))
        except HomeAssistantError:
            raise
        except ValueError as exc:
            raise HomeAssistantError(str(exc)) from exc
        except Exception as exc:
            coordinator.connection_failed(exc)
            raise HomeAssistantError("模式执行中断，部分设置可能已生效；请查看状态后重试") from exc
