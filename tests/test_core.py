import unittest
from fixtures import core, ops, capture, state, identity


class ProtocolTests(unittest.TestCase):
    def test_fragmented_and_concatenated_notifications(self):
        for model in core.PROFILES:
            frames = capture(model)
            expected = [core.parse(model, raw) for raw in frames]
            for size in (1, 2, 7, 20, 500):
                stream = core.FrameStream(model)
                data = b''.join(frames)
                actual = []
                for pos in range(0, len(data), size):
                    actual.extend(stream.feed(data[pos:pos+size]))
                self.assertEqual(actual, expected)

    def test_corrupt_checksum_noise_and_buffer_limit(self):
        for model in core.PROFILES:
            raw = capture(model)[0]
            damaged = bytearray(raw)
            damaged[-2] ^= 1
            self.assertEqual(core.FrameStream(model).feed(b'noise' + damaged + raw), [core.parse(model, raw)])
            with self.assertRaises(ValueError):
                core.FrameStream(model).feed(b'x' * 4097)

    def test_fc_escape_roundtrip_and_rejection(self):
        raw = bytearray(capture('sq9650')[0])
        raw[22:24] = b'\xfc\xfd'
        raw[1] = sum(raw[2:-1]) & 255
        escaped = b'\xfc' + bytes(raw[1:-1]).replace(b'\xfd', b'\xfd\x02').replace(b'\xfc', b'\xfd\x01') + b'\xfc'
        self.assertEqual(core.unescape(escaped), raw)
        with self.assertRaises(ValueError): core.unescape(b'\xfc\xfd\x03\xfc')

    def test_model_limits_and_invalid_values(self):
        for model, key, value in [('sq9650','seat_temp_level',2), ('sq9650','water_temp_level',1),
                                  ('zs800j','air_temp',5), ('zs800j','wind_speed',0),
                                  ('zs800j','foam_time',5), ('zs800j','cover_sensitivity',2),
                                  ('zs800j','water_temp_level',True), ('sq9650','auto_flush','false')]:
            with self.assertRaises(ValueError): core.setting_frame(model,key,value,state(model))

    def test_no_write_from_missing_busy_or_faulted_state(self):
        for change in [{'seated':True}, {'work_state':16}, {'flush_running':True},
                       {'temperature_fault':True}, {'device_fault':True}, {'hip_nozzle':0}]:
            with self.assertRaises(ValueError):
                core.setting_frame('zs800j','water_temp_level',1,{**state('zs800j'), **change})
        for key in ('hip_nozzle','wind_speed','gesture','seated'):
            before=state('zs800j'); del before[key]
            with self.assertRaises(KeyError): core.setting_frame('zs800j','seat_temp_level',1,before)

    def test_temperature_change_preserves_other_payload_bytes(self):
        before=state('zs800j')
        low=core.setting_frame('zs800j','water_temp_level',0,before)
        high=core.setting_frame('zs800j','water_temp_level',5,before)
        self.assertEqual([i for i,(a,b) in enumerate(zip(low,high)) if a != b], [6,17])
        self.assertEqual(high[5], 0x19)
        self.assertEqual(high[6] >> 4, 5)

    def test_fixed_control_vectors(self):
        self.assertEqual(core.setting_frame('sq9650','night_light',True,state('sq9650')).hex(), 'fc4301000000410001fc')
        self.assertEqual(core.setting_frame('sq9650','seat_temp_level',0,state('sq9650')).hex(), 'fc3d010000003c00fc')
        self.assertEqual(core.setting_frame('zs800j','cover_sensitivity',1,state('zs800j')).hex(), 'f3f40692211f1000e8fc')

    def test_automatic_light_blocks_manual_light(self):
        with self.assertRaises(ValueError):
            core.setting_frame('sq9650','night_light',True,{**state('sq9650'),'light_sensor':True})

    def test_prewetting_only_permits_model_specific_coupling(self):
        before={'prewetting':False, 'auto_bubble':False, 'uv_water':False}
        after={**before,'prewetting':True,'auto_bubble':True}
        core.verify_setting_changes('zs800j','prewetting',True,before,after)
        with self.assertRaises(RuntimeError): core.verify_setting_changes('sq9650','prewetting',True,before,after)
        with self.assertRaises(RuntimeError): core.verify_setting_changes('zs800j','prewetting',True,before,{**after,'uv_water':True})
        core.verify_setting_changes('zs800j','prewetting',False,after,before)
        with self.assertRaises(RuntimeError): core.verify_setting_changes('zs800j','prewetting',False,after,{**before,'auto_bubble':True})

    def test_short_e2_does_not_parse_checksum_as_foam(self):
        original=capture('zs800j')[0]
        raw=bytearray(original[:10]+b'\x00\xfc');raw[2]=len(raw)-4;raw[-2]=sum(raw[2:-2])&255
        self.assertNotIn('foam_time',core.parse('zs800j',raw)[1])

    def test_motion_requires_idle_and_model_allowlist(self):
        for model in core.PROFILES:
            for action in ops.ACTIONS[model]:
                if action=='stop_clean': continue
                for change in [{'seated':True},{'cover_running':True},{'device_fault':True}]:
                    with self.assertRaises(ValueError): ops.action_frame(model,action,{**state(model),**change})
        with self.assertRaises(ValueError): ops.action_frame('sq9650','nozzle_clean',state('sq9650'))

    def test_action_feedback_is_not_just_any_frame(self):
        self.assertFalse(ops.action_done('zs800j','open_cover',{'cover_open':True,'cover_running':True}))
        self.assertTrue(ops.action_done('zs800j','open_cover',{'cover_open':True,'cover_running':False}))
        self.assertFalse(ops.action_done('zs800j','replace_nozzle',{'work_state':3}))
        self.assertTrue(ops.action_done('zs800j','replace_nozzle',{'work_state':131}))
        self.assertEqual(ops.action_frame('zs800j','stop_clean',{**state('zs800j'),'work_state':131})[5],0)


class IdentityTests(unittest.TestCase):
    def test_normalization(self):
        self.assertEqual(identity.normalize_address(' aa-bb-cc-dd-ee-01 '),'AA:BB:CC:DD:EE:01')
        for value in ('','aa:bb','GG:BB:CC:DD:EE:01','AA:BB:CC:DD:EE:001'):
            with self.assertRaises(ValueError): identity.normalize_address(value)

    def test_same_model_distinct_identity(self):
        a=identity.entity_prefix('sq9650','AA:BB:CC:DD:EE:01')
        b=identity.entity_prefix('sq9650','AA:BB:CC:DD:EE:02')
        self.assertNotEqual(a,b)
        self.assertEqual(a,'jomoo_sq9650_aabbccddee01')
