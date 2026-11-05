import asyncio
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('scheduling', Path(__file__).resolve().parent.parent / 'custom_components/jomoo_local/scheduling.py')
scheduling = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scheduling)


class SchedulingTests(unittest.IsolatedAsyncioTestCase):
    async def test_commands_pass_waiting_reads_but_preserve_command_order(self):
        q = scheduling.OperationQueue()
        order = []
        async def run(name, priority):
            async with q.slot(priority): order.append(name)
        async with q.slot():
            tasks = []
            for name, priority in [('poll', 2), ('on', 1), ('off', 1), ('release', 0)]:
                tasks.append(asyncio.create_task(run(name, priority)))
                await asyncio.sleep(0)
        await asyncio.gather(*tasks)
        self.assertEqual(order, ['release', 'on', 'off', 'poll'])

    async def test_cancelled_waiter_and_failed_owner_do_not_block_queue(self):
        q = scheduling.OperationQueue()
        async def run():
            async with q.slot(): return 'ok'
        with self.assertRaises(ValueError):
            async with q.slot():
                cancelled = asyncio.create_task(run())
                await asyncio.sleep(0)
                cancelled.cancel()
                with self.assertRaises(asyncio.CancelledError): await cancelled
                raise ValueError('failed owner')
        self.assertEqual(await asyncio.wait_for(run(), 1), 'ok')

    async def test_two_devices_do_not_block_each_other(self):
        a, b = scheduling.OperationQueue(), scheduling.OperationQueue()
        async with a.slot():
            async with b.slot(): pass
