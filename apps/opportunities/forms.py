"""Opportunity filters and forms."""
from django import forms

from apps.clients.models import Client

from .models import Opportunity

UF_CHOICES = [
    ("", "UF"),
    ("AC", "AC"), ("AL", "AL"), ("AM", "AM"), ("AP", "AP"),
    ("BA", "BA"), ("CE", "CE"), ("DF", "DF"), ("ES", "ES"),
    ("GO", "GO"), ("MA", "MA"), ("MG", "MG"), ("MS", "MS"),
    ("MT", "MT"), ("PA", "PA"), ("PB", "PB"), ("PE", "PE"),
    ("PI", "PI"), ("PR", "PR"), ("RJ", "RJ"), ("RN", "RN"),
    ("RO", "RO"), ("RR", "RR"), ("RS", "RS"), ("SC", "SC"),
    ("SE", "SE"), ("SP", "SP"), ("TO", "TO"),
]

SORT_CHOICES = [
    ("-published_at", "Mais recentes"),
    ("deadline", "Prazo (mais proximo)"),
    ("-deadline", "Prazo (mais distante)"),
    ("-estimated_value", "Valor (maior)"),
    ("estimated_value", "Valor (menor)"),
]


class OpportunityFilterForm(forms.Form):
    """Filter form for opportunity list."""

    q = forms.CharField(
        label="Busca", required=False,
        widget=forms.TextInput(attrs={"placeholder": "Buscar objeto ou orgao..."}),
    )
    status = forms.ChoiceField(
        label="Status", required=False,
        choices=[("", "Todos")] + list(Opportunity.Status.choices),
    )
    modality = forms.ChoiceField(
        label="Modalidade", required=False,
        choices=[("", "Todas")] + list(Opportunity.Modality.choices),
    )
    uf = forms.ChoiceField(label="UF", required=False, choices=UF_CHOICES)
    source = forms.ChoiceField(
        label="Fonte", required=False,
        choices=[("", "Todas")] + list(Opportunity.Source.choices),
    )
    sort = forms.ChoiceField(
        label="Ordenar", required=False, choices=SORT_CHOICES,
    )


class RunAIForm(forms.Form):
    """Form to trigger AI analysis."""

    analysis_type = forms.ChoiceField(choices=[
        ("full", "Analise Completa"),
        ("summary", "Resumo Executivo"),
        ("checklist", "Checklist de Habilitacao"),
        ("risks", "Riscos e Pegadinhas"),
    ])


class RunMatchingForm(forms.Form):
    """Form to trigger matching against a client."""

    client = forms.ModelChoiceField(
        queryset=Client.objects.filter(is_active=True),
        label="Cliente",
    )
