"""API URL configuration."""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

app_name = "api"

router = DefaultRouter()
router.register("clients", views.ClientViewSet)
router.register("opportunities", views.OpportunityViewSet)

urlpatterns = [
    path("", include(router.urls)),
]

# ── Exemplo de payloads ────────────────────────────────
#
# GET /api/opportunities/?status=new&entity_uf=SP&search=tecnologia
# Response:
# {
#   "count": 42,
#   "results": [
#     {
#       "id": "uuid",
#       "source": "pncp",
#       "title": "Aquisição de equipamentos de TI",
#       "entity_name": "Prefeitura de São Paulo",
#       "entity_uf": "SP",
#       "estimated_value": "150000.00",
#       "status": "new",
#       ...
#     }
#   ]
# }
#
# POST /api/opportunities/{uuid}/run_ai/
# {"analysis_type": "full"}
# Response: {"status": "enqueued", "analysis_type": "full"}
#
# POST /api/opportunities/{uuid}/run_matching/
# {"client_id": "uuid-do-cliente"}
# Response: {"status": "enqueued", "client_id": "uuid-do-cliente"}
