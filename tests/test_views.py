"""Integration tests for views."""
import pytest
from django.urls import reverse


class TestOpportunityViews:
    def test_list_requires_login(self, client):
        resp = client.get(reverse("opportunities:list"))
        assert resp.status_code == 302
        assert "/accounts/login/" in resp.url

    def test_list_authenticated(self, auth_client):
        resp = auth_client.get(reverse("opportunities:list"))
        assert resp.status_code == 200

    def test_detail_view(self, auth_client, sample_opportunity):
        resp = auth_client.get(
            reverse("opportunities:detail", kwargs={"pk": sample_opportunity.pk})
        )
        assert resp.status_code == 200
        assert "Aquisição" in resp.content.decode()


class TestClientViews:
    def test_list_requires_login(self, client):
        resp = client.get(reverse("clients:list"))
        assert resp.status_code == 302

    def test_list_authenticated(self, auth_client):
        resp = auth_client.get(reverse("clients:list"))
        assert resp.status_code == 200

    def test_create_client(self, auth_client):
        resp = auth_client.post(reverse("clients:create"), {
            "name": "Nova Empresa",
            "cnpj": "99.888.777/0001-66",
            "regions_input": "SP, MG",
            "keywords_input": "teste, software",
            "categories_input": "TI",
        })
        assert resp.status_code == 302  # redirect on success
