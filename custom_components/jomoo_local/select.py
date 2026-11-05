from homeassistant.components.select import SelectEntity
from .core import SELECTS, SELECT_LABELS
from .entity import JomooEntity
from .presets import PresetEntity
from .preset_config import MODES, fields
from .core import SWITCHES


async def async_setup_entry(hass, entry, async_add_entities):
    c = entry.runtime_data
    async_add_entities([JomooSelect(c, k, v) for k, v in SELECTS[c.model].items()] +
                       [PresetSelect(c, mode, key) for mode in MODES for key in fields(c.model)])


class JomooSelect(JomooEntity, SelectEntity):
    domain = "select"

    def __init__(self, coordinator, key, options):
        super().__init__(coordinator, key, SELECT_LABELS[key])
        self.values = options
        self._attr_options = list(options)

    @property
    def current_option(self):
        level = (self.coordinator.data or {}).get(self.key)
        return next((k for k, v in self.values.items() if v == level), None)

    async def async_select_option(self, option):
        await self.coordinator.set_setting(self.key, self.values[option])


class PresetSelect(PresetEntity, SelectEntity):
    def __init__(self, coordinator, mode, key):
        name = SWITCHES[coordinator.model].get(key, SELECT_LABELS.get(key, key))
        super().__init__(coordinator, mode, key, name, "select")
        self._attr_options = list(fields(coordinator.model)[key])

    @property
    def current_option(self):
        return self.presets.data[self.mode][self.key]

    async def async_select_option(self, option):
        await self.async_save(option)
