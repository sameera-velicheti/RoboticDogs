"""Closing one dog's connection must not break the other dogs' connections."""

from ros2_bridge.ros_nodes import RosPugBridge


class FakeClient:
    def __init__(self):
        self.closed = self.terminated = False

    def close(self):
        self.closed = True

    def terminate(self):          # stops the event loop for EVERY dog
        self.terminated = True


class FakeTopic:
    def unadvertise(self):
        pass


def test_closing_one_dog_does_not_stop_the_shared_event_loop():
    bridge = RosPugBridge.__new__(RosPugBridge)   # skip connecting
    bridge.client = FakeClient()
    bridge.publisher = FakeTopic()
    bridge.stop = lambda: None

    bridge.close()

    assert bridge.client.closed
    assert not bridge.client.terminated
