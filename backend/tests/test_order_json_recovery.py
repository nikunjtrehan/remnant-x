"""A successful HTTP response is not necessarily a usable manufacturing order."""
from copy import deepcopy

import pytest

from backend.m2_spark_orchestrator import SparkWarehouseOrchestrator

PROMPT = "Cut 10 circles, each 50 mm in diameter, from 0.1 mm ss304 sheet. Kerf 0.2 mm."
VALID = {"material": "ss304", "thickness_mm": 0.1, "kerf_mm": 0.2,
         "parts": [{"part_id": "DISC", "shape_type": "circle", "quantity": 10, "diameter_mm": 50}]}


class ModelResponses:
    def __init__(self, payloads, fireworks=False):
        self.payloads = iter(payloads)
        self.has_fireworks = fireworks
        self.calls = 0

    def chat_completion(self, **kwargs):
        self.calls += 1
        payload = next(self.payloads)
        return {"ok": payload != "offline", "provider": kwargs["prefer_provider"], "model": "test",
                "parsed_json": deepcopy(payload) if isinstance(payload, dict) else None,
                "content": "", "reasoning_content": "", "usage": {},
                "error": "unavailable" if payload == "offline" else None}


@pytest.mark.parametrize("repair", [None, "offline", "malformed"])
def test_exact_recording_prompt_recovers_unusable_model_json(repair):
    responses = [None] if repair is None else [None, repair]
    model = ModelResponses(responses, fireworks=repair is not None)
    orch = SparkWarehouseOrchestrator(None, model)
    order = orch.parse_natural_language_order_via_spark(PROMPT)
    assert (order.material, order.thickness_mm, order.kerf_mm) == ("ss304", 0.1, 0.2)
    assert [(p.shape_type, p.quantity, p.diameter_mm) for p in order.parts] == [("circle", 10, 50)]
    assert orch.last_llm_trace["provider"] == "local-deterministic-fallback"
    assert model.calls == len(responses)


def test_exact_recording_prompt_also_works_when_cloud_is_unreachable():
    order = SparkWarehouseOrchestrator(None, ModelResponses(["offline"])).parse_natural_language_order_via_spark(PROMPT)
    assert order.parts[0].quantity == 10 and order.parts[0].diameter_mm == 50


def test_valid_fireworks_repair_still_uses_the_model_order():
    orch = SparkWarehouseOrchestrator(None, ModelResponses([None, VALID], fireworks=True))
    assert orch.parse_natural_language_order_via_spark(PROMPT).parts[0].quantity == 10
    assert orch.last_llm_trace["provider"] == "fireworks"


def test_malformed_repair_preserves_original_requirement_violation():
    wrong = deepcopy(VALID)
    wrong["parts"][0]["quantity"] = 11
    orch = SparkWarehouseOrchestrator(None, ModelResponses([wrong, None], fireworks=True))
    with pytest.raises(ValueError, match="ERR_ORDER_NEEDS_CLARIFICATION"):
        orch.parse_natural_language_order_via_spark(PROMPT)


def test_semantically_wrong_repair_is_not_silently_accepted_or_replaced():
    wrong = deepcopy(VALID)
    wrong["material"] = "ss316"
    with pytest.raises(ValueError, match="ERR_MODEL_CHANGED_MATERIAL_GRADE"):
        SparkWarehouseOrchestrator(None, ModelResponses([None, wrong], fireworks=True)).parse_natural_language_order_via_spark(PROMPT)


def test_recording_prompt_recovers_through_http_without_touching_inventory(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from backend.api import create_app

    model = ModelResponses([None, "offline"], fireworks=True)
    monkeypatch.setattr("backend.api.LiveModelClient", lambda: model)
    db_file = tmp_path / "untouched.sqlite"
    response = TestClient(create_app(str(db_file), str(tmp_path / "artifacts"))).post(
        "/api/v1/parse-order", json={"prompt": PROMPT})
    assert response.status_code == 200, response.text
    assert response.json()["order"]["parts"][0]["quantity"] == 10
    assert response.json()["llm_trace"]["provider"] == "local-deterministic-fallback"
    assert not db_file.exists()
