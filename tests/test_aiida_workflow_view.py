from __future__ import annotations

from src.aris_apps.aiida.presenters import workflow_view


def test_enrich_submission_draft_keeps_cutoffs_under_parameters() -> None:
    payload = {
        "process_label": "quantumespresso.pw.relax",
        "inputs": {
            "base": {
                "pw": {
                    "parameters": {
                        "SYSTEM": {
                            "ecutwfc": 60,
                            "ecutrho": 480,
                        }
                    }
                }
            }
        },
        "recommended_inputs": {
            "ecutwfc": 60,
            "ecutrho": 480,
        },
        "meta": {},
    }

    normalized = workflow_view.enrich_submission_draft_payload(payload)
    all_inputs = normalized["all_inputs"]

    assert "ecutwfc" not in all_inputs
    assert "ecutrho" not in all_inputs
    assert "base.pw.parameters.SYSTEM.ecutwfc" in all_inputs
    assert "base.pw.parameters.SYSTEM.ecutrho" in all_inputs


def test_enrich_submission_draft_adds_available_codes_metadata(monkeypatch) -> None:
    fake_codes = [
        {
            "value": "pw@localhost",
            "label": "pw@localhost",
            "code_label": "pw",
            "computer_label": "localhost",
            "plugin": "quantumespresso.pw",
            "pk": 11,
        }
    ]

    monkeypatch.setattr(workflow_view, "_query_available_codes", lambda _required_plugin: fake_codes)

    payload = {
        "process_label": "quantumespresso.pw.relax",
        "inputs": {
            "base": {
                "pw": {
                    "code": "pw@localhost",
                    "parameters": {"SYSTEM": {"ecutwfc": 60}},
                }
            }
        },
        "meta": {},
    }

    normalized = workflow_view.enrich_submission_draft_payload(payload)
    meta = normalized["meta"]

    assert meta["required_code_plugin"] == "quantumespresso.pw"
    assert meta["available_codes"] == fake_codes
    port_spec = meta["port_spec"]
    assert {"base", "base.pw", "base.pw.parameters"}.issubset(set(port_spec["namespaces"]))
    assert port_spec["code_paths"] == ["base.pw.code"]
    assert meta["workchain_entry_point"] == "quantumespresso.pw.relax"


def test_enrich_submission_draft_builds_input_port_spec_and_codes(monkeypatch) -> None:
    monkeypatch.setattr(workflow_view, "_query_available_codes", lambda _required_plugin: [])

    payload = {
        "process_label": "PwRelaxWorkChain",
        "inputs": {
            "code": "pw-7.5@localhost",
            "base": {
                "pw": {
                    "code": "pw-7.5@localhost",
                    "parameters": {"SYSTEM": {"ecutwfc": 60}},
                }
            },
        },
        "meta": {},
    }

    normalized = workflow_view.enrich_submission_draft_payload(payload)
    meta = normalized["meta"]
    port_spec = meta["port_spec"]
    namespaces = set(port_spec["namespaces"])

    assert "base" in namespaces
    assert port_spec["code_paths"] == ["base.pw.code", "code"]
    assert any(entry["value"] == "pw-7.5@localhost" for entry in meta["available_codes"])


def test_enrich_submission_draft_treats_node_envelopes_as_single_editable_inputs() -> None:
    payload = {
        "process_label": "ExampleWorkChain",
        "inputs": {
            "Nbands_Factor": {
                "pk": None,
                "uuid": "draft-node-1",
                "type": "Float",
                "value": 1.5,
            },
            "kpoints_distance": {
                "pk": None,
                "uuid": "draft-node-2",
                "type": "Float",
                "value": 0.2,
            },
        },
        "meta": {},
    }

    normalized = workflow_view.enrich_submission_draft_payload(payload)
    all_inputs = normalized["all_inputs"]

    assert "Nbands_Factor" in all_inputs
    assert all_inputs["Nbands_Factor"]["value"] == 1.5
    assert "Nbands_Factor.pk" not in all_inputs
    assert "Nbands_Factor.uuid" not in all_inputs
    assert "Nbands_Factor.type" not in all_inputs

    assert "kpoints_distance" in all_inputs
    assert all_inputs["kpoints_distance"]["value"] == 0.2
    assert "kpoints_distance.pk" not in all_inputs

    groups = normalized["input_groups"]
    computational = next(entry for entry in groups if entry.get("id") == "computational_details")
    computational_paths = {
        property_entry["path"]
        for port in computational["ports"]
        for property_entry in port["properties"]
    }
    assert "Nbands_Factor" in computational_paths

    brillouin_zone = next(entry for entry in groups if entry.get("id") == "brillouin_zone")
    brillouin_paths = {
        property_entry["path"]
        for port in brillouin_zone["ports"]
        for property_entry in port["properties"]
    }
    assert "kpoints_distance" in brillouin_paths


def test_format_worker_batch_submission_response_preserves_worker_metadata() -> None:
    raw = {
        "status": "SUBMITTED_BATCH",
        "total": 2,
        "submitted_count": 2,
        "failed_count": 0,
        "submitted_pks": [101, 102],
        "responses": [
            {"index": 0, "response": {"pk": 101}},
            {"index": 1, "response": {"pk": 102}},
        ],
        "failures": [],
        "batch_context": {"matrix_mode": "product"},
    }

    formatted = workflow_view.format_worker_batch_submission_response(raw)

    assert formatted["status"] == "SUBMITTED_BATCH"
    assert formatted["submitted_pks"] == [101, 102]
    assert formatted["process_pks"] == [101, 102]
    assert formatted["total"] == 2
    assert formatted["submitted_count"] == 2
    assert formatted["failed_count"] == 0
    assert formatted["batch_context"] == {"matrix_mode": "product"}


def test_enrich_submission_draft_prefers_builder_inputs_over_raw_node_envelopes() -> None:
    payload = {
        "process_label": "ExampleWorkChain",
        "inputs": {
            "Nbands_Factor": {
                "pk": None,
                "uuid": "draft-node-1",
                "type": "Float",
            },
            "settings": {
                "pk": None,
                "uuid": "draft-node-2",
                "type": "Dict",
            },
        },
        "meta": {
            "validation": {
                "builder_inputs": {
                    "Nbands_Factor": 1.5,
                    "settings": {"SYSTEM": {"ecutwfc": 60}},
                }
            }
        },
    }

    normalized = workflow_view.enrich_submission_draft_payload(payload)
    all_inputs = normalized["all_inputs"]

    assert normalized["inputs"]["Nbands_Factor"] == 1.5
    assert normalized["inputs"]["settings"] == {"SYSTEM": {"ecutwfc": 60}}
    assert all_inputs["Nbands_Factor"]["value"] == 1.5
    assert all_inputs["settings.SYSTEM.ecutwfc"]["value"] == 60


def test_query_available_codes_uses_worker_resources(monkeypatch) -> None:
    from src.aris_apps.aiida import client as aiida_client

    def fake_call_sync(method: str, params=None, **kwargs):
        _ = kwargs
        
        assert method == "resource.summary"
        return {
            "codes": [
                {
                    "label": "qe-750-pw",
                    "computer_label": "lucia",
                    "default_plugin": "quantumespresso.pw",
                },
                {
                    "label": "qe-750-ph",
                    "computer_label": "lucia",
                    "default_plugin": "quantumespresso.ph",
                },
                {
                    "value": "qe-alt@lucia",
                },
            ]
        }

    monkeypatch.setattr(aiida_client.aiida_worker_client, "call_sync", fake_call_sync)

    codes = workflow_view._query_available_codes("quantumespresso.pw")
    codes_by_value = {str(item.get("value")): item for item in codes}

    assert "qe-750-pw@lucia" in codes_by_value
    assert codes_by_value["qe-750-pw@lucia"]["is_compatible"] is True
    assert "qe-750-ph@lucia" in codes_by_value
    assert "qe-alt@lucia" in codes_by_value
