import hashlib
from django.db import models


class ScrapedProduct(models.Model):
    # identity
    url        = models.URLField(max_length=2000)
    url_hash   = models.CharField(max_length=64, unique=True, db_index=True)
    # extracted fields
    name       = models.CharField(max_length=500, null=True, blank=True)
    brand      = models.CharField(max_length=200, null=True, blank=True)
    price      = models.CharField(max_length=50,  null=True, blank=True)
    currency   = models.CharField(max_length=10,  null=True, blank=True)
    image      = models.URLField(max_length=2000, null=True, blank=True)
    image_s3   = models.URLField(max_length=2000, null=True, blank=True)
    source     = models.CharField(max_length=200, null=True, blank=True)

    # pipeline metadata
    layer_used  = models.CharField(max_length=50, null=True, blank=True)
    is_complete = models.BooleanField(default=False)
    confidence  = models.FloatField(default=0.0)

    # timestamps
    scraped_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-scraped_at"]
        verbose_name = "Scraped Product"
        verbose_name_plural = "Scraped Products"

    def __str__(self):
        return f"{self.name or 'Unknown'} ({self.source})"

    @staticmethod
    def make_hash(url: str) -> str:
        return hashlib.sha256(url.encode()).hexdigest()

