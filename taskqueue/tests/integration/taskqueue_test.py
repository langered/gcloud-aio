# pylint: disable=too-many-locals
import asyncio
import json
import os
import uuid

import aiohttp
from gcloud.aio.taskqueue import decode
from gcloud.aio.taskqueue import encode
from gcloud.aio.taskqueue import TaskQueue


async def do_task_lifecycle(project, creds, task_queue):
    with aiohttp.ClientSession() as session:
        tq = TaskQueue(project, creds, task_queue, session=session)

        payload = {'this': {'is': {'a': {'test': uuid.uuid4().hex}}}}
        tag = 'smoke-test'

        # DRAIN
        await tq.drain()

        # INSERT
        inserted = await tq.insert(encode(json.dumps(payload)),
                                   tag=encode(tag))
        assert inserted

        # GET
        got = await tq.get(inserted['name'], full=True)
        assert got == inserted

        # LIST
        listed = await tq.list(full=True)
        assert listed.get('tasks')
        assert inserted in listed['tasks']

        # LEASE
        leased = await tq.lease(num_tasks=1, lease_seconds=10,
                                task_filter='tag={}'.format(encode(tag)))
        assert leased.get('tasks') and len(leased['tasks']) == 1

        leased_message = leased['tasks'][0]['pullMessage']
        leased_payload = json.loads(decode(leased_message['payload']))
        leased_tag = decode(leased_message['tag'])
        assert leased_payload == payload
        assert leased_tag == tag

        # RENEW
        renewed = await tq.renew(leased['tasks'][0], lease_seconds=10)
        for k, v in renewed.items():
            if k == 'scheduleTime':
                assert v != leased['tasks'][0][k]
            else:
                assert v == leased['tasks'][0][k]

        # ack?
        # cancel?

        # DELETE
        result = await tq.delete(renewed['name'])
        assert not result


def test_task_lifecycle():
    project = os.environ['GCLOUD_PROJECT']
    creds = os.environ['GOOGLE_APPLICATION_CREDENTIALS']

    task_queue = 'test-pull'

    loop = asyncio.get_event_loop()
    loop.run_until_complete(
        do_task_lifecycle(project, creds, task_queue))