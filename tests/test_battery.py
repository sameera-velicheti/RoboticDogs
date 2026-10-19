"""Battery: millivolts from the dog -> percentage on the dog card."""

import time

import pytest

from status import battery


@pytest.fixture(autouse=True)
def clean():
    battery._readings.clear()
    battery._watching.clear()


def test_full_and_empty():
    assert battery.volts_to_percent(12.6) == 100
    assert battery.volts_to_percent(9.6) == 0


def test_nominal_is_about_half():
    assert 40 <= battery.volts_to_percent(11.46) <= 60


def test_todays_pumbaa_reading_is_low():
    # 10247 mV seen on Pumbaa on Oct 19
    assert battery.volts_to_percent(10.247) <= 10


def test_percentage_never_goes_up_as_voltage_drops():
    values = [battery.volts_to_percent(v / 100) for v in range(1300, 900, -5)]
    assert values == sorted(values, reverse=True)


def test_reading_is_averaged_and_flagged_low():
    battery._record("dog1", 11000)
    battery._record("dog1", 11200)
    info = battery.battery("dog1")
    assert info["volts"] == 11.1
    assert info["low"] is False or info["percent"] <= battery.LOW_PERCENT


def test_no_reading_means_none():
    assert battery.battery("dog1") is None


def test_stale_reading_means_none(monkeypatch):
    battery._record("dog1", 12000)
    later = time.time() + battery.STALE_SECONDS + 1
    monkeypatch.setattr(battery.time, "time", lambda: later)
    assert battery.battery("dog1") is None


def test_watch_does_not_block_and_resubscribes_when_quiet(monkeypatch):
    started = []
    monkeypatch.setattr(battery, "_subscribe", lambda dog_id: started.append(dog_id))
    battery.watch("dog1")
    battery.watch("dog1")            # already connecting: no second subscribe
    time.sleep(0.05)
    assert started == ["dog1"]

    later = time.time() + battery.STALE_SECONDS + 1
    monkeypatch.setattr(battery.time, "time", lambda: later)
    battery.watch("dog1")            # quiet too long: subscribe again
    time.sleep(0.05)
    assert started == ["dog1", "dog1"]


def test_dog_card_includes_battery(monkeypatch):
    import app as flask_app
    from startup import dog_prep
    monkeypatch.setattr(dog_prep, "dog_status", lambda dog: ("ready", "Ready for patrol"))
    monkeypatch.setattr(battery, "watch", lambda dog_id: None)
    battery._record("dog1", 12200)

    dogs = flask_app.app.test_client().get("/api/dogs").get_json()["dogs"]
    pumbaa = next(d for d in dogs if d["id"] == "dog1")
    assert pumbaa["battery"] >= 80
    assert pumbaa["battery_volts"] == 12.2