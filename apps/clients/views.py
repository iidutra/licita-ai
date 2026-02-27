"""Client views — CRUD with documents."""
import logging
import re

import httpx
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
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
    success_url = reverse_lazy("clients:list")


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


def cnpj_lookup(request):
    """AJAX endpoint — busca dados de CNPJ via BrasilAPI."""
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

    return JsonResponse({
        "cnpj": data.get("cnpj", digits),
        "razao_social": data.get("razao_social", ""),
        "nome_fantasia": data.get("nome_fantasia", ""),
        "email": data.get("email", ""),
        "telefone": data.get("ddd_telefone_1", ""),
        "uf": data.get("uf", ""),
        "municipio": data.get("municipio", ""),
        "situacao": data.get("descricao_situacao_cadastral", ""),
        "atividade_principal": (
            data.get("cnae_fiscal_descricao", "")
        ),
    })
