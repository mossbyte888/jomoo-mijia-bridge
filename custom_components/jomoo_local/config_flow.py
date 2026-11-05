"""Configure a supported model and the user's own Bluetooth address."""
import voluptuous as vol
from homeassistant import config_entries
from .const import DOMAIN
from .core import PROFILES
from .identity import normalize_address


class JomooFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                address = normalize_address(user_input['address'])
            except ValueError:
                errors['address'] = 'invalid_address'
            else:
                model = user_input['model']
                await self.async_set_unique_id(address)
                self._abort_if_unique_id_configured()
                title = user_input.get('name', '').strip() or '九牧 ' + PROFILES[model]['name']
                return self.async_create_entry(title=title, data={'model': model, 'address': address})
        return self.async_show_form(
            step_id='user', errors=errors,
            data_schema=vol.Schema({
                vol.Required('model'): vol.In({k: v['name'] for k, v in PROFILES.items()}),
                vol.Required('address'): str,
                vol.Optional('name', default=''): str,
            }),
        )
