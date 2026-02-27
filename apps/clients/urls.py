"""Client URL patterns."""
from django.urls import path

from . import views

app_name = "clients"

urlpatterns = [
    path("", views.ClientListView.as_view(), name="list"),
    path("create/", views.ClientCreateView.as_view(), name="create"),
    path("api/cnpj-lookup/", views.cnpj_lookup, name="cnpj_lookup"),
    path("<uuid:pk>/", views.ClientDetailView.as_view(), name="detail"),
    path("<uuid:pk>/edit/", views.ClientUpdateView.as_view(), name="edit"),
    path("<uuid:pk>/documents/add/", views.add_client_document, name="add_document"),
]
