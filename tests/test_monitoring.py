"""Tests for the procurement monitoring engine."""
import pytest

from apps.connectors.monitoring import (
    detect_changes,
    event_dedup_hash,
    persist_events,
)
from apps.opportunities.models import OpportunityEvent


class TestEventDedupHash:
    def test_deterministic(self):
        h1 = event_dedup_hash("abc", "status_change", "closed")
        h2 = event_dedup_hash("abc", "status_change", "closed")
        assert h1 == h2

    def test_different_values_different_hashes(self):
        h1 = event_dedup_hash("abc", "status_change", "closed")
        h2 = event_dedup_hash("abc", "status_change", "open")
        assert h1 != h2

    def test_different_opp_ids_different_hashes(self):
        h1 = event_dedup_hash("abc", "status_change", "closed")
        h2 = event_dedup_hash("xyz", "status_change", "closed")
        assert h1 != h2

    def test_different_event_types_different_hashes(self):
        h1 = event_dedup_hash("abc", "status_change", "val")
        h2 = event_dedup_hash("abc", "deadline_changed", "val")
        assert h1 != h2


@pytest.mark.django_db
class TestDetectChanges:
    def test_status_change(self, monitored_opportunity):
        fresh_data = {
            **monitored_opportunity.raw_data,
            "situacaoCompraId": 5,
            "situacaoCompraNome": "Homologada",
        }
        events = detect_changes(monitored_opportunity, fresh_data, [], [], [])
        assert len(events) == 1
        assert events[0]["event_type"] == OpportunityEvent.EventType.STATUS_CHANGE
        assert events[0]["new_value"] == "Homologada"
        assert events[0]["old_value"] == "Divulgada"

    def test_deadline_changed(self, monitored_opportunity):
        fresh_data = {
            **monitored_opportunity.raw_data,
            "dataEncerramentoProposta": "2026-05-15T18:00:00-03:00",
        }
        events = detect_changes(monitored_opportunity, fresh_data, [], [], [])
        assert len(events) == 1
        assert events[0]["event_type"] == OpportunityEvent.EventType.DEADLINE_CHANGED

    def test_new_document(self, monitored_opportunity):
        fresh_docs = [
            {"url": "https://pncp.gov.br/doc/123.pdf", "file_name": "edital.pdf", "doc_type": "Edital"},
        ]
        events = detect_changes(monitored_opportunity, monitored_opportunity.raw_data, fresh_docs, [], [])
        assert len(events) == 1
        assert events[0]["event_type"] == OpportunityEvent.EventType.NEW_DOCUMENT
        assert "edital.pdf" in events[0]["new_value"]

    def test_no_change(self, monitored_opportunity):
        events = detect_changes(
            monitored_opportunity,
            monitored_opportunity.raw_data,
            [],
            [],
            [],
        )
        assert events == []

    def test_value_changed(self, monitored_opportunity):
        fresh_data = {
            **monitored_opportunity.raw_data,
            "valorTotalHomologado": 450000.00,
        }
        events = detect_changes(monitored_opportunity, fresh_data, [], [], [])
        assert len(events) == 1
        assert events[0]["event_type"] == OpportunityEvent.EventType.VALUE_CHANGED

    def test_result_published(self, monitored_opportunity):
        fresh_results = [
            {
                "_itemNumero": 1,
                "nomeRazaoSocialFornecedor": "Tech LTDA",
                "valorTotalHomologado": 120000,
            },
        ]
        events = detect_changes(
            monitored_opportunity, monitored_opportunity.raw_data, [], fresh_results, [],
        )
        assert len(events) == 1
        assert events[0]["event_type"] == OpportunityEvent.EventType.RESULT_PUBLISHED

    def test_ata_published(self, monitored_opportunity):
        fresh_atas = [{"numeroAta": "001/2024"}]
        events = detect_changes(
            monitored_opportunity, monitored_opportunity.raw_data, [], [], fresh_atas,
        )
        assert len(events) == 1
        assert events[0]["event_type"] == OpportunityEvent.EventType.ATA_PUBLISHED


@pytest.mark.django_db
class TestPersistEvents:
    def test_creates_events(self, monitored_opportunity):
        event_dicts = [
            {
                "event_type": OpportunityEvent.EventType.STATUS_CHANGE,
                "old_value": "Divulgada",
                "new_value": "Homologada",
                "description": "Status alterado",
                "raw_data": {},
            },
        ]
        created = persist_events(monitored_opportunity, event_dicts)
        assert len(created) == 1
        assert OpportunityEvent.objects.filter(opportunity=monitored_opportunity).count() == 1

    def test_idempotent(self, monitored_opportunity):
        event_dicts = [
            {
                "event_type": OpportunityEvent.EventType.STATUS_CHANGE,
                "old_value": "Divulgada",
                "new_value": "Homologada",
                "description": "Status alterado",
                "raw_data": {},
            },
        ]
        # Run twice — second time should not create duplicates
        persist_events(monitored_opportunity, event_dicts)
        created_2nd = persist_events(monitored_opportunity, event_dicts)
        assert len(created_2nd) == 0
        assert OpportunityEvent.objects.filter(opportunity=monitored_opportunity).count() == 1
