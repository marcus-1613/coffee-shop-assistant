"""
数据新鲜度接口测试

验证 /datasource/freshness 返回「多数据源」结构，且诚实标注疫情数据停更。
"""
from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


class TestFreshness:
    def test_returns_sources_list(self):
        """返回 sources 列表，包含天气/疫情/经营数据三类"""
        resp = client.get("/datasource/freshness")
        assert resp.status_code == 200
        data = resp.json()
        assert "sources" in data
        names = {s["name"] for s in data["sources"]}
        assert {"open-meteo", "disease-sh", "sqlite"} <= names

    def test_each_source_has_label_and_note(self):
        """每个数据源都有 label 和 note（诚实披露）"""
        resp = client.get("/datasource/freshness")
        data = resp.json()
        for s in data["sources"]:
            assert "label" in s
            assert "note" in s
            assert "status" in s

    def test_disease_sh_note_mentions_stale(self):
        """疫情数据源 note 必须提示停更（数据诚实）"""
        resp = client.get("/datasource/freshness")
        data = resp.json()
        disease = next(s for s in data["sources"] if s["name"] == "disease-sh")
        assert "停更" in disease["note"] or "2023" in disease["note"]
