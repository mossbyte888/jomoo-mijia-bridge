from homeassistant.components.button import ButtonEntity
from .entity import JomooEntity
from .operations import ACTIONS
from .presets import async_apply
from .preset_config import MODES


async def async_setup_entry(hass, entry, async_add_entities):
    c = entry.runtime_data
    async_add_entities([JomooButton(c, key, label) for key, label in ACTIONS[c.model].items()] +
                       [PresetButton(c, mode) for mode in MODES])


class JomooButton(JomooEntity, ButtonEntity):
    domain = "button"

    @property
    def available(self):
        if self.coordinator.released:
            return False
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
