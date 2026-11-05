from homeassistant.components.button import ButtonEntity
from .entity import JomooEntity
from .operations import ACTIONS
from .presets import async_apply
from .preset_config import MODES


async def async_setup_entry(hass, entry, async_add_entities):
    c = entry.runtime_data
    async_add_entities([JomooButton(c, key, label) for key, label in ACTIONS[c.model].items()] +
                       [PresetButton(c, mode) for mode in MODES] + [RefreshButton(c)])


class JomooButton(JomooEntity, ButtonEntity):
    domain = "button"

    @property
    def available(self):
        if self.coordinator.released or self.coordinator.stopping:
            return False
        if not self.coordinator.persistent:
            return True
        return bool(self.coordinator.data) if self.key == "stop_clean" else self.coordinator.last_update_success

    async def async_press(self):
        await self.coordinator.perform_action(self.key)


class PresetButton(JomooButton):
    def __init__(self, coordinator, mode):
        super().__init__(coordinator, f"apply_{mode}", f"应用{MODES[mode]}")
        self.mode = mode
        self._attr_icon = "mdi:leaf" if mode == "eco" else "mdi:tune"

    async def async_press(self):
        await async_apply(self.coordinator, self.mode)


class RefreshButton(JomooButton):
    def __init__(self, coordinator):
        super().__init__(coordinator, "refresh_state", "读取状态（按需连接）")
        self._attr_icon = "mdi:refresh"

    @property
    def available(self):
        return not self.coordinator.released and not self.coordinator.stopping

    async def async_press(self):
        async with self.coordinator.operation():
            try:
                self.coordinator.accept_state(await self.coordinator.exchange())
            except Exception as exc:
                self.coordinator.connection_failed(exc)
                raise
