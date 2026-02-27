from django.contrib import admin

from .models import Match


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = ["client", "opportunity_short", "score", "prompt_version", "created_at"]
    list_filter = ["score", "model_name"]
    search_fields = ["client__name", "opportunity__title"]

    @admin.display(description="Oportunidade")
    def opportunity_short(self, obj):
        return obj.opportunity.title[:80]
