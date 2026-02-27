from django.contrib import admin

from .models import Client, ClientDocument


class ClientDocumentInline(admin.TabularInline):
    model = ClientDocument
    extra = 0


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ["name", "cnpj", "email", "is_active", "created_at"]
    list_filter = ["is_active", "regions"]
    search_fields = ["name", "cnpj", "trade_name"]
    inlines = [ClientDocumentInline]


@admin.register(ClientDocument)
class ClientDocumentAdmin(admin.ModelAdmin):
    list_display = ["client", "doc_type", "status", "expires_at"]
    list_filter = ["doc_type", "status"]
