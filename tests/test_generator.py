import importlib.util
import unittest
from fixtures import ROOT, core, ops

spec=importlib.util.spec_from_file_location('generator',ROOT/'scripts/generate_config.py')
generator=importlib.util.module_from_spec(spec);spec.loader.exec_module(generator)


class GeneratorTests(unittest.TestCase):
    def test_routes_and_dashboard_agree_with_component_entities(self):
        devices=[('bath_a','sq9650','AA:BB:CC:DD:EE:01'),('bath_b','sq9650','AA:BB:CC:DD:EE:02'),('zs','zs800j','AA:BB:CC:DD:EE:03')]
        auto,dashboard,table=generator.build(devices,'event.example_gateway',True)
        entities=set()
        for view in dashboard['views']:
            for card in view['cards']:
                entities.update(row['entity'] for row in card.get('entities',[]))
        for name,route in auto['variables']['routes'].items():
            self.assertIn(route['entity'],entities)
            self.assertIn(name,table)
            self.assertIn(route['action'],['button.press','switch.turn_on','switch.turn_off','select.select_option'])
        self.assertNotEqual(auto['variables']['routes']['jomoo_bath_a_night_light_on']['entity'], auto['variables']['routes']['jomoo_bath_b_night_light_on']['entity'])

    def test_default_route_has_no_physical_actions(self):
        auto,_,_=generator.build([('zs','zs800j','AA:BB:CC:DD:EE:01')],'event.example_gateway')
        self.assertFalse(any(r['action']=='button.press' for r in auto['variables']['routes'].values()))
        self.assertEqual(auto['variables']['routes']['jomoo_zs_seat_temp_level_2']['option'],'偏低')

    def test_invalid_and_duplicate_devices_rejected(self):
        for raw in ['wrong','sq=unknown=AA:BB:CC:DD:EE:01','bad-name=sq9650=AA:BB:CC:DD:EE:01']:
            with self.assertRaises(generator.argparse.ArgumentTypeError): generator.parse_device(raw)
        d=('sq','sq9650','AA:BB:CC:DD:EE:01')
        with self.assertRaises(ValueError): generator.build([d,d],'event.gateway')
        with self.assertRaises(ValueError): generator.build([d,('zs','zs800j',d[2])],'event.gateway')
        with self.assertRaises(ValueError): generator.build([d],'notify.gateway')

    def test_checked_in_examples_are_reproducible(self):
        import json
        a,d,t=generator.build([('sq9650','sq9650','AA:BB:CC:DD:EE:01'),('zs800j','zs800j','AA:BB:CC:DD:EE:02')],'event.example_gateway_virtual_event')
        self.assertEqual(a,json.loads((ROOT/'examples/automation.yaml').read_text()))
        self.assertEqual(d,json.loads((ROOT/'examples/dashboard.yaml').read_text()))
        self.assertEqual(t,(ROOT/'examples/米家事件名称.md').read_text())
