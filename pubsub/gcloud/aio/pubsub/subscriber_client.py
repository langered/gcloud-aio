from gcloud.aio.auth import BUILD_GCLOUD_REST  # pylint: disable=no-name-in-module

if BUILD_GCLOUD_REST:
    class FlowControl:
        def __init__(self, **kwargs) -> None:
            raise NotImplementedError('this class is only implemented in aio')

    class SubscriberClient:
        def __init__(self, **kwargs) -> None:
            raise NotImplementedError('this class is only implemented in aio')

else:
    import asyncio
    import concurrent.futures
    import signal
    from typing import Any
    from typing import Callable
    from typing import Optional

    from google.api_core import exceptions
    from google.cloud import pubsub
    from google.cloud.pubsub_v1.subscriber.message import Message

    from .subscriber_message import SubscriberMessage
    from .utils import convert_google_future_to_concurrent_future


    class FlowControl(tuple):
        def __init__(self,
                     max_bytes: int = 100 * 1024 * 1024,
                     max_messages: int = 1000,
                     max_lease_duration: int = 1 * 60 * 60,
                     max_duration_per_lease_extension: int = 0) -> None:
            super(FlowControl, self).__init__()
            self.max_bytes = max_bytes
            self.max_messages = max_messages
            self.max_lease_duration = max_lease_duration
            self.max_duration_per_lease_extension = (
                max_duration_per_lease_extension)


    class SubscriberClient:
        def __init__(self, *, loop: Optional[asyncio.AbstractEventLoop] = None,
                     **kwargs: Any) -> None:
            self._subscriber = pubsub.SubscriberClient(**kwargs)
            self.loop = loop or asyncio.get_event_loop()

        def create_subscription(self,
                                subscription: str,
                                topic: str,
                                **kwargs
                                ) -> None:
            """
            Create subscription if it does not exist. Check out the official
            [create_subscription docs](https://github.com/googleapis/google-cloud-python/blob/11c72ade8b282ae1917fba19e7f4e0fe7176d12b/pubsub/google/cloud/pubsub_v1/gapic/subscriber_client.py#L236)  # pylint: disable=line-too-long
            for more details
            """
            try:
                self._subscriber.create_subscription(
                    subscription,
                    topic,
                    **kwargs
                )
            except exceptions.AlreadyExists:
                pass

        def subscribe(self,
                      subscription: str,
                      callback: Callable[[SubscriberMessage], None],
                      *,
                      flow_control: FlowControl = ()
                      ) -> asyncio.Future:
            """
            Create subscription through pubsub client, hijack the returned
            "non-concurrent Future" and coerce it into being a "concurrent
            Future", wrap it into a asyncio Future and return it.
            """
            sub_keepalive: asyncio.Future = self._subscriber.subscribe(
                subscription,
                self._wrap_callback(callback),
                flow_control=flow_control
            )

            convert_google_future_to_concurrent_future(
                sub_keepalive, loop=self.loop
            )
            _ = asyncio.wrap_future(sub_keepalive)
            self.loop.add_signal_handler(signal.SIGTERM, sub_keepalive.cancel)

            return sub_keepalive

        def run_forever(self, sub_keepalive: asyncio.Future) -> None:
            """
            Start the asyncio loop, running until it is either SIGTERM-ed or
            killed by keyboard interrupt. The Future parameter is used to
            cancel subscription Future in the case that an unexpected exception
            is thrown. You can also directly pass the `.subscribe()` method
            call instead like so:
                sub.run_forever(sub.subscribe(callback))
            """
            try:
                self.loop.run_forever()
            except (KeyboardInterrupt, concurrent.futures.CancelledError):
                pass
            finally:
                # 1. stop the `SubscriberClient` future, which will prevent
                #    more tasks from being leased
                if not sub_keepalive.cancelled():
                    sub_keepalive.cancel()
                # 2. cancel the tasks we already have, which should just be
                #    `worker` instances; note they have
                #    `except CancelledError: pass`
                for task in asyncio.Task.all_tasks(loop=self.loop):
                    task.cancel()
                # 3. stop the `asyncio` event loop
                self.loop.stop()

        def _wrap_callback(self,
                           callback: Callable[[SubscriberMessage], None]
                           ) -> Callable[[Message], None]:
            """Schedule callback to be called from the event loop"""
            def _callback_wrapper(message: Message) -> None:
                asyncio.run_coroutine_threadsafe(
                    callback(SubscriberMessage.from_google_cloud(message)),
                    self.loop)

            return _callback_wrapper
