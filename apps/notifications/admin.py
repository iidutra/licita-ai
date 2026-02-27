from django.contrib import admin

from .models import EventNotification


@admin.register(EventNotification)
class EventNotificationAdmin(admin.ModelAdmin):
    list_display = ["event_type", "channel", "subject", "delivery_status", "created_at"]
    list_filter = ["event_type", "channel", "delivery_status"]
    search_fields = ["subject", "body"]
    readonly_fields = ["created_at", "sent_at"]
