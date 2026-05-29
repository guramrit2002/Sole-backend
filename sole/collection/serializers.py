from rest_framework import serializers
from scraper.serializers import ScrapedProductSerializer
from .models import Collection


class CollectionSerializer(serializers.ModelSerializer):
    shoes      = ScrapedProductSerializer(many=True, read_only=True)
    shoe_count = serializers.SerializerMethodField()

    class Meta:
        model  = Collection
        fields = ["id", "name", "description", "tags", "shoes", "shoe_count",
                  "total_worth", "total_shoes", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_shoe_count(self, obj):
        return obj.shoes.count()


class CollectionWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Collection
        fields = ["name", "description", "tags"]
