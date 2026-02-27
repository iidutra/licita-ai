"""Opportunity views — list, detail, actions (AI, matching), PDF export."""
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.views.generic import DetailView, ListView

from .forms import OpportunityFilterForm, RunAIForm, RunMatchingForm
from .models import Opportunity
from .parser import format_brl
from .services import (
    aggregate_risks,
    build_action_checklist,
    build_kpi_cards,
    build_summary_context,
    compute_timeline,
    derive_smart_chips,
    extract_go_nogo,
)

ALLOWED_SORT_FIELDS = {
    "-published_at", "published_at",
    "-deadline", "deadline",
    "-estimated_value", "estimated_value",
}


class OpportunityListView(LoginRequiredMixin, ListView):
    model = Opportunity
    template_name = "opportunities/opportunity_list.html"
    context_object_name = "opportunities"
    paginate_by = 25

    def get_queryset(self):
        qs = super().get_queryset()
        form = OpportunityFilterForm(self.request.GET)
        if form.is_valid():
            d = form.cleaned_data
            if d.get("q"):
                qs = qs.filter(
                    Q(title__icontains=d["q"])
                    | Q(entity_name__icontains=d["q"])
                )
            if d.get("status"):
                qs = qs.filter(status=d["status"])
            if d.get("modality"):
                qs = qs.filter(modality=d["modality"])
            if d.get("uf"):
                qs = qs.filter(entity_uf=d["uf"].upper())
            if d.get("source"):
                qs = qs.filter(source=d["source"])
            sort = d.get("sort", "-published_at") or "-published_at"
            if sort in ALLOWED_SORT_FIELDS:
                qs = qs.order_by(sort)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["filter_form"] = OpportunityFilterForm(self.request.GET)
        ctx["total_count"] = Opportunity.objects.count()
        ctx["new_count"] = Opportunity.objects.filter(status=Opportunity.Status.NEW).count()

        # Preserve filter params in pagination links
        query = self.request.GET.copy()
        query.pop("page", None)
        ctx["filter_query"] = query.urlencode()

        # Active filter chips (for removable chips UI)
        ctx["active_filters"] = self._active_filters()
        return ctx

    def _active_filters(self) -> list[dict]:
        """Build list of applied filters for chip display."""
        chips: list[dict] = []
        g = self.request.GET
        if g.get("status"):
            label = dict(Opportunity.Status.choices).get(g["status"], g["status"])
            chips.append({"param": "status", "label": label})
        if g.get("modality"):
            label = dict(Opportunity.Modality.choices).get(g["modality"], g["modality"])
            chips.append({"param": "modality", "label": label})
        if g.get("uf"):
            chips.append({"param": "uf", "label": g["uf"].upper()})
        if g.get("source"):
            label = dict(Opportunity.Source.choices).get(g["source"], g["source"])
            chips.append({"param": "source", "label": label})
        if g.get("q"):
            chips.append({"param": "q", "label": f'"{g["q"]}"'})
        return chips


class OpportunityDetailView(LoginRequiredMixin, DetailView):
    model = Opportunity
    template_name = "opportunities/opportunity_detail.html"
    context_object_name = "opp"

    def _build_dashboard_context(self, opp):
        items = list(opp.items.all())
        documents = opp.documents.all()
        requirements = list(opp.requirements.all())
        ai_summaries = list(opp.ai_summaries.order_by("-created_at"))
        matches = list(opp.matches.select_related("client").order_by("-score"))

        summary_ctx = build_summary_context(ai_summaries)

        return {
            "items": items,
            "documents": documents,
            "requirements": requirements,
            "ai_summaries": ai_summaries,
            "matches": matches,
            "smart_chips": derive_smart_chips(opp),
            "go_nogo": extract_go_nogo(ai_summaries),
            "timeline": compute_timeline(opp),
            "kpi_cards": build_kpi_cards(opp, items, matches),
            "risks": aggregate_risks(ai_summaries),
            "checklist_groups": build_action_checklist(requirements),
            **summary_ctx,
        }

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        opp = self.object
        ctx.update(self._build_dashboard_context(opp))
        ctx["ai_form"] = RunAIForm()
        ctx["matching_form"] = RunMatchingForm()
        return ctx


class RunAIView(LoginRequiredMixin, View):
    def post(self, request, pk):
        opp = get_object_or_404(Opportunity, pk=pk)
        form = RunAIForm(request.POST)
        if form.is_valid():
            from apps.ai_engine.tasks import run_ai_analysis
            run_ai_analysis.delay(str(opp.pk), form.cleaned_data["analysis_type"])
            messages.success(request, "Analise IA enfileirada com sucesso.")
        else:
            messages.error(request, "Formulario invalido.")
        return redirect("opportunities:detail", pk=pk)


class RunMatchingView(LoginRequiredMixin, View):
    def post(self, request, pk):
        opp = get_object_or_404(Opportunity, pk=pk)
        form = RunMatchingForm(request.POST)
        if form.is_valid():
            from apps.matching.tasks import run_matching
            client = form.cleaned_data["client"]
            run_matching.delay(str(opp.pk), str(client.pk))
            messages.success(request, f"Matching com {client.name} enfileirado.")
        else:
            messages.error(request, "Selecione um cliente.")
        return redirect("opportunities:detail", pk=pk)


class ChangeStatusView(LoginRequiredMixin, View):
    def post(self, request, pk):
        opp = get_object_or_404(Opportunity, pk=pk)
        new_status = request.POST.get("status")
        if new_status in dict(Opportunity.Status.choices):
            opp.status = new_status
            opp.save(update_fields=["status", "updated_at"])
            messages.success(request, f"Status alterado para {opp.get_status_display()}.")
        return redirect("opportunities:detail", pk=pk)


class ExportPDFView(LoginRequiredMixin, DetailView):
    """Print-friendly page for PDF export via ``window.print()``."""

    model = Opportunity
    template_name = "opportunities/opportunity_pdf.html"
    context_object_name = "opp"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        opp = self.object
        ctx.update(OpportunityDetailView._build_dashboard_context(None, opp))
        return ctx
