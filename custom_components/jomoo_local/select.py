from homeassistant.components.select import SelectEntity
from .core import SELECTS, SELECT_LABELS
from .entity import JomooEntity


async def async_setup_entry(hass, entry, async_add_entities):
    c = entry.runtime_data
    async_add_entities(JomooSelect(c, k, v) for k, v in SELECTS[c.model].items())


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
