from app.injector import Injector
from tests.conftest import FakeBackend


def make():
    backend = FakeBackend()
    return Injector(backend), backend


def test_shared_key_goes_down_once_and_up_when_last_owner_releases():
    inj, backend = make()
    inj.press_keys(("d1", "a"), ["w"])
    inj.press_keys(("d1", "b"), ["w"])  # second owner: no second key-down (no fake key repeat)
    inj.release_keys(("d1", "a"), ["w"])
    assert backend.log == [("key", "w", True)]
    inj.release_keys(("d1", "b"), ["w"])
    assert backend.log == [("key", "w", True), ("key", "w", False)]


def test_chord_releases_in_reverse_order():
    inj, backend = make()
    inj.press_keys(("d", "x"), ["ctrl", "c"])
    inj.release_keys(("d", "x"), ["ctrl", "c"])
    assert [e[1] for e in backend.log if not e[2]] == ["c", "ctrl"]


def test_release_owners_only_touches_matching_device():
    inj, _ = make()
    inj.press_keys((1, "a"), ["a"])
    inj.press_keys((2, "a"), ["b"])
    inj.press_button((1, "t"), "left")
    assert sorted(inj.release_owners(lambda o: o[0] == 1)) == ["a", "left"]
    assert inj.held() == ["b"]
    inj.release_all()
    assert inj.held() == []


def test_retrigger_splits_fast_taps_but_not_holds():
    inj, backend = make()
    inj.press_keys(("tap", 1), ["e"], retrigger=True)
    inj.press_keys(("tap", 2), ["e"], retrigger=True)
    assert backend.log == [("key", "e", True), ("key", "e", False), ("key", "e", True)]
    inj2, backend2 = make()
    inj2.press_keys((1, "hold"), ["e"])
    inj2.press_keys(("tap", 1), ["e"], retrigger=True)
    assert backend2.log == [("key", "e", True)]


def test_backend_errors_do_not_escape():
    class Broken:
        def key(self, *_):
            raise OSError("blocked")

    inj = Injector(Broken())
    inj.press_keys(("d", "a"), ["a"])
    inj.release_all()
    assert inj.held() == []
