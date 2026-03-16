"""Client views — CRUD with documents."""
import logging
import re

import httpx
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from .forms import ClientDocumentForm, ClientForm
from .models import Client, ClientDocument

logger = logging.getLogger(__name__)


class ClientListView(LoginRequiredMixin, ListView):
    model = Client
    template_name = "clients/client_list.html"
    context_object_name = "clients"
    paginate_by = 25


class ClientCreateView(LoginRequiredMixin, CreateView):
    model = Client
    form_class = ClientForm
    template_name = "clients/client_form.html"

    def get_success_url(self):
        return reverse("clients:detail", kwargs={"pk": self.object.pk})


class ClientUpdateView(LoginRequiredMixin, UpdateView):
    model = Client
    form_class = ClientForm
    template_name = "clients/client_form.html"
    success_url = reverse_lazy("clients:list")


class ClientDetailView(LoginRequiredMixin, DetailView):
    model = Client
    template_name = "clients/client_detail.html"
    context_object_name = "client"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["documents"] = self.object.documents.all()
        ctx["doc_form"] = ClientDocumentForm()
        ctx["matches"] = self.object.matches.select_related("opportunity").order_by("-score")[:20]

        # Quick matches: fast DB-level suggestions (always shown)
        from apps.matching.quick_match import quick_match
        ctx["quick_matches"] = quick_match(self.object, limit=10)

        return ctx


def add_client_document(request, pk):
    """Add a document to a client (POST only)."""
    client = get_object_or_404(Client, pk=pk)
    if request.method == "POST":
        form = ClientDocumentForm(request.POST, request.FILES)
        if form.is_valid():
            doc = form.save(commit=False)
            doc.client = client
            doc.save()
    return redirect("clients:detail", pk=pk)


def trigger_quick_match(request, pk, opp_pk):
    """Trigger AI matching for a specific client-opportunity pair."""
    if request.method != "POST":
        return redirect("clients:detail", pk=pk)

    client = get_object_or_404(Client, pk=pk)
    from apps.matching.tasks import run_matching
    run_matching.delay(str(opp_pk), str(client.pk))
    messages.success(request, "Matching com IA enfileirado.")
    return redirect("clients:detail", pk=pk)


def cnpj_lookup(request):
    """AJAX endpoint — busca dados de CNPJ via BrasilAPI + Dados Abertos."""
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Não autenticado"}, status=401)

    raw = request.GET.get("cnpj", "")
    digits = re.sub(r"\D", "", raw)

    if len(digits) != 14:
        return JsonResponse({"error": "CNPJ deve ter 14 dígitos"}, status=400)

    try:
        resp = httpx.get(
            f"https://brasilapi.com.br/api/cnpj/v1/{digits}",
            timeout=10,
            follow_redirects=True,
        )
        if resp.status_code == 404:
            return JsonResponse({"error": "CNPJ não encontrado na Receita Federal"}, status=404)
        resp.raise_for_status()
        data = resp.json()
    except httpx.TimeoutException:
        return JsonResponse({"error": "Timeout ao consultar CNPJ"}, status=504)
    except Exception:
        logger.exception("CNPJ lookup failed for %s", digits)
        return JsonResponse({"error": "Erro ao consultar CNPJ"}, status=502)

    result = {
        "cnpj": data.get("cnpj", digits),
        "razao_social": data.get("razao_social", ""),
        "nome_fantasia": data.get("nome_fantasia", ""),
        "email": data.get("email", ""),
        "telefone": data.get("ddd_telefone_1", ""),
        "uf": data.get("uf", ""),
        "municipio": data.get("municipio", ""),
        "situacao": data.get("descricao_situacao_cadastral", ""),
        "atividade_principal": data.get("cnae_fiscal_descricao", ""),
    }

    # Enrich with Dados Abertos (compras.gov.br) — optional, non-blocking
    try:
        gov_resp = httpx.get(
            f"https://compras.dados.gov.br/fornecedores/v1/fornecedor/{digits}.json",
            timeout=8,
            follow_redirects=True,
        )
        if gov_resp.status_code == 200:
            gov = gov_resp.json()
            result["dados_abertos"] = {
                "ativo": gov.get("ativo", None),
                "porte_empresa": gov.get("porte_empresa", ""),
                "ramo_negocio": gov.get("ramo_negocio", ""),
                "natureza_juridica": gov.get("natureza_juridica", ""),
            }
    except Exception:
        pass  # Enrichment is optional

    return JsonResponse(result)
