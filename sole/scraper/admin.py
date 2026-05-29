from django.contrib import admin
from .models import ScrapedProduct


@admin.register(ScrapedProduct)
class ScrapedProductAdmin(admin.ModelAdmin):
    list_display  = ("name", "brand", "price", "currency", "source", "layer_used", "is_complete", "scraped_at")
    list_filter   = ("is_complete", "layer_used", "currency", "source")
    search_fields = ("name", "brand", "url")
    readonly_fields = ("url_hash", "scraped_at", "updated_at")
    ordering      = ("-scraped_at",)
