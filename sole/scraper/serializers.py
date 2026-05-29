from rest_framework import serializers
from .models import ScrapedProduct


class ScrapeRequestSerializer(serializers.Serializer):
    url   = serializers.URLField()
    force = serializers.BooleanField(
        default=False, required=False,
        help_text="Set true to re-scrape even if URL is already cached",
    )


class ScrapedProductSerializer(serializers.ModelSerializer):
    class Meta:
        model  = ScrapedProduct
        fields = [
            "id", "url", "name", "price", "currency",
            "image", "image_s3", "source", "layer_used", "is_complete",
            "confidence", "scraped_at",
        ]
        read_only_fields = fields
