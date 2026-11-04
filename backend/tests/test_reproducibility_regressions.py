"""Fresh-workspace and material-context regressions found in the submission audit."""
from fastapi.testclient import TestClient
import pytest
from shapely.geometry import box

from backend.api import create_app
from backend.db_and_parts import RemnantWarehouseDB
from backend.materials import explicit_prompt_materials


def test_new_nested_workspace_persists_and_reopens(tmp_path):
    path = tmp_path / "new workshop" / "inventory" / "warehouse.sqlite"
    db = RemnantWarehouseDB(str(path))
    db.upsert_remnant("A", "ss304", 0.1, box(0, 0, 100, 80))
    reopened = RemnantWarehouseDB(str(path))
    assert reopened.get_remnant("A").polygon.equals(box(0, 0, 100, 80))


def test_fresh_api_workspace_is_lazy_and_starts_empty(tmp_path):
    path = tmp_path / "new workspace" / "warehouse.sqlite"
    app = create_app(str(path), str(tmp_path / "artifacts"))
    with TestClient(app) as client:
        assert client.get("/api/v1/health").status_code == 200
        assert not path.exists()
        response = client.get("/api/v1/remnants")
        assert response.status_code == 200
        assert response.json() == {"count": 0, "remnants": []}
    assert path.is_file()


@pytest.mark.parametrize("prompt_material,selected_material", [
    ("copper", "ss304"), ("acrylic", "al6061"), ("ss316", "ss304"),
    ("steel", "acrylic"),
    ("plexiglass", "ss304"), ("copper", "steel"),
])
def test_conflicting_prompt_and_selected_stock_stop_before_model(
    tmp_path, monkeypatch, prompt_material, selected_material
):
    app = create_app(str(tmp_path / "warehouse.sqlite"), str(tmp_path / "artifacts"))
    calls = []
    def unexpected_call(**kwargs):
        calls.append(kwargs)
        return {"ok": True, "provider": "test", "model": "test", "content": "",
                "reasoning_content": "", "usage": {}, "parsed_json": {
                    "material": selected_material, "thickness_mm": 3, "kerf_mm": 1,
                    "parts": [{"shape_type": "circle", "quantity": 2, "diameter_mm": 20}],
                }}
    monkeypatch.setattr(app.state.llm, "chat_completion", unexpected_call)
    response = TestClient(app).post("/api/v1/parse-order", json={
        "prompt": f"Cut 2 circles, diameter 20 mm, from 3 mm {prompt_material} sheet. Kerf 1 mm.",
        "stock": {"material": selected_material, "thickness_mm": 3, "kerf_mm": 1},
    })
    assert response.status_code == 422, response.text
    assert "ERR_ORDER_NEEDS_CLARIFICATION" in response.json()["detail"]
    assert not calls


@pytest.mark.parametrize("text,expected", [
    ("3 mm stainless steel 304 sheet", {"ss304"}),
    ("3 mm 6061 aluminum sheet", {"al6061"}),
    ("3 mm SS304 steel sheet", {"ss304"}),
    ("3 mm SS304 sheet and 3 mm copper sheet", {"ss304", "copper"}),
])
def test_material_mentions_preserve_grades_and_other_families(text, expected):
    assert explicit_prompt_materials(text) == expected
