"""Root URL configuration."""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from django.views.generic import RedirectView


def health_check(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("health/", health_check, name="health_check"),
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),
    path("clients/", include("apps.clients.urls", namespace="clients")),
    path("opportunities/", include("apps.opportunities.urls", namespace="opportunities")),
    path("api/", include("apps.api.urls", namespace="api")),
    path("", RedirectView.as_view(url="/opportunities/", permanent=False)),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

admin.site.site_header = "LicitaAI Admin"
admin.site.site_title = "LicitaAI"
admin.site.index_title = "Painel Administrativo"
