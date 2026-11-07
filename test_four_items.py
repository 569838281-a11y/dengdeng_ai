"""动作词可见、点头后续跑、文件与算式、拆开的小问。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_action_word_is_visible_and_calc_is_limited():
    from agents.surf_agents import safe_calc

    assert safe_calc("1+2*3") == 7
    try:
        safe_calc("__import__('os').system('echo hi')")
        raised = False
    except Exception:
        raised = True
    assert raised


def test_file_surfer_stays_inside_the_allowed_dirs():
    from agents.surf_agents import _find, _inside

    found = _find("读一下水灵")
    assert found is not None
    assert found.stem == "水灵"
    assert _inside(found)
    assert _find("读一下C:/Windows/win.ini") is None


def test_same_run_continues_after_approval():
    from agents.cycle_graph import drive, resume_held
    from agents.job_ledger import blank, drop
    from agents.write_confirm import arm, disarm

    def warehouse(_text, _sid):
        from agents.write_confirm import stage_table

        stage_table("hold_probe.csv", "name\n海枝枝\n", "预览仓库", "灯灯记下了仓库。", "仓库")
        return {"ok": True, "answer": "灯灯记下了仓库。"}

    book = blank("hold-case", "记一下")
    book["constraints"]["intent"] = "order"
    book["progress"]["next"] = "need_write"
    held = arm("hold-case", "job-hold")
    try:
        drive(book, session_id="hold-case", warehouse=warehouse)
        assert book["progress"]["next"] == "hold"
        thread = book["progress"]["thread_id"]
        assert thread
        again = resume_held(thread, True)
    finally:
        disarm(held)
        drop("hold-case")
        probe = ROOT / "data" / "party" / "hold_probe.csv"
        if probe.is_file():
            probe.unlink()
    assert "记下" in (again.get("speech") or "")


if __name__ == "__main__":
    test_action_word_is_visible_and_calc_is_limited()
    test_file_surfer_stays_inside_the_allowed_dirs()
    test_same_run_continues_after_approval()
    print("ok")
