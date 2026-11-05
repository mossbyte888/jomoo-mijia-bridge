from homeassistant.components.button import ButtonEntity
from .entity import JomooEntity
from .operations import ACTIONS


async def async_setup_entry(hass, entry, async_add_entities):
    c = entry.runtime_data
    async_add_entities(JomooButton(c, key, label) for key, label in ACTIONS[c.model].items())


class JomooButton(JomooEntity, ButtonEntity):
    domain = "button"

    @property
    def available(self):
        if self.coordinator.released:
            return False
        return bool(self.coordinator.data) if self.key == "stop_clean" else self.coordinator.last_update_success

    async def async_press(self):
        await self.coordinator.perform_action(self.key)
