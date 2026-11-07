"""知识库要人确认才改，并能按快照退回。文档写入同样先预览。"""
import tempfile
from pathlib import Path

import agents.write_gate as write_gate
from agents.knowledge_revision import confirm, propose, rollback


def test_knowledge_confirm_and_rollback():
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        target = root / "knowledge" / "pokemon"
        target.mkdir(parents=True)
        page = target / "水灵.json"
        page.write_text('{"name":"水灵"}', encoding="utf-8")
        pending = propose(root, "knowledge/pokemon/水灵.json", '{"name":"水灵","trait":"浸润"}')
        assert page.read_text(encoding="utf-8") == '{"name":"水灵"}'
        assert confirm(root, pending["token"])["status"] == "applied"
        assert "浸润" in page.read_text(encoding="utf-8")
        assert rollback(root, pending["token"])["status"] == "rolled_back"
        assert page.read_text(encoding="utf-8") == '{"name":"水灵"}'
        assert (root / "data" / "knowledge_revisions" / "log.jsonl").is_file()


def test_private_path_is_refused():
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        try:
            propose(root, ".env", "KEY=1")
        except ValueError:
            return
        raise AssertionError("private path was accepted")


def test_document_write_waits_for_confirm():
    with tempfile.TemporaryDirectory() as folder:
        old = write_gate.DATA_DIR
        write_gate.DATA_DIR = folder
        try:
            token = write_gate.stage("lineup.docx", "水灵记下了。", "docx")
            assert not (Path(folder) / "party" / "lineup.docx").exists()
            name = write_gate.commit(token)
            assert (Path(folder) / "party" / name).is_file()
        finally:
            write_gate.DATA_DIR = old


if __name__ == "__main__":
    test_knowledge_confirm_and_rollback()
    test_private_path_is_refused()
    test_document_write_waits_for_confirm()
    print("ok")
