"""Opportunity URL patterns."""
from django.urls import path

from . import views

app_name = "opportunities"

urlpatterns = [
    path("", views.OpportunityListView.as_view(), name="list"),
    path("<uuid:pk>/", views.OpportunityDetailView.as_view(), name="detail"),
    path("<uuid:pk>/run-ai/", views.RunAIView.as_view(), name="run_ai"),
    path("<uuid:pk>/run-matching/", views.RunMatchingView.as_view(), name="run_matching"),
    path("<uuid:pk>/change-status/", views.ChangeStatusView.as_view(), name="change_status"),
    path("<uuid:pk>/export-pdf/", views.ExportPDFView.as_view(), name="export_pdf"),
]
