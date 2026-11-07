"""仓库和出场在确认前不改表。没说只数时仍然只问，不弹出确认。"""
import tempfile
from pathlib import Path

from agents import battle_orders, write_confirm
from agents.battle_orders import _change_warehouse, hold_table


class _Patch:
    def __init__(self):
        self.saved = []

    def __enter__(self):
        self.folder = Path(tempfile.mkdtemp())
        self._dir = write_confirm._dir
        self._write = battle_orders._write_table
        write_confirm._dir = lambda: self.folder
        battle_orders._write_table = lambda path, text: self.saved.append((path, text))
        return self

    def __exit__(self, *_args):
        write_confirm._dir = self._dir
        battle_orders._write_table = self._write


def test_armed_hold_waits_until_confirm():
    with _Patch() as patch:
        token = write_confirm.arm("session-a", "job-a")
        try:
            pending = hold_table(
                "warehouse.csv",
                "name,count\n水灵,2\n",
                "灯灯准备在仓库里多放两只水灵。确认后才记下。",
                "灯灯帮你在仓库里多放了两只水灵。",
                "仓库",
            )
            assert pending["token"]
            assert patch.saved == []
            assert write_confirm.take()["token"] == pending["token"]
            assert write_confirm.list_pending("session-a")[0]["preview"].startswith("灯灯准备")
        finally:
            write_confirm.disarm(token)
        saved = write_confirm.commit(pending["token"])
        assert patch.saved == [("warehouse.csv", "name,count\n水灵,2\n")]
        assert saved["text"] == "灯灯帮你在仓库里多放了两只水灵。"
        assert write_confirm.list_pending("session-a") == []


def test_reject_leaves_the_table():
    with _Patch() as patch:
        token = write_confirm.arm("session-b", "job-b")
        try:
            pending = hold_table(
                "teams.csv",
                "id,slot\n",
                "灯灯准备记下第 1 套出场。确认后才记下。",
                "灯灯记下了第 1 套出场。",
                "第 1 套出场",
            )
        finally:
            write_confirm.disarm(token)
        assert write_confirm.reject(pending["token"])["text"] == "灯灯没有记下。"
        assert patch.saved == []
        try:
            write_confirm.commit(pending["token"])
        except FileNotFoundError:
            return
        raise AssertionError("拒绝之后不应该还能记下")


def test_missing_count_does_not_stage():
    with _Patch():
        token = write_confirm.arm("session-c", "job-c")
        try:
            sentence, ok = _change_warehouse({"name": "水灵", "delta": -1}, "放生海枝枝")
        finally:
            write_confirm.disarm(token)
        assert ok is False
        assert sentence == "告诉灯灯改几只。"
        assert write_confirm.take() == {}


if __name__ == "__main__":
    test_armed_hold_waits_until_confirm()
    test_reject_leaves_the_table()
    test_missing_count_does_not_stage()
    print("ok")
