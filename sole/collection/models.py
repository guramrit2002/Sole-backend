from django.db import models
from django.conf import settings
from scraper.models import ScrapedProduct
# Create your models here.

class Collection(models.Model):
    user        = models.ForeignKey(settings.AUTH_USER_MODEL, 
                                    on_delete=models.CASCADE, 
                                    related_name="collections")
    name        = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    tags        = models.JSONField(default=list, blank=True)
    shoes       = models.ManyToManyField(ScrapedProduct,
                                         through='ShoeCollection', 
                                         related_name='collections', blank=True)   
    
    total_shoes = models.IntegerField(default=0)
    total_worth = models.FloatField(default=0.0)
    
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        ordering        = ["-created_at"]
        unique_together = [("user", "name")]

    def __str__(self):
        return f"{self.user.email} / {self.name}"

class ShoeCollection(models.Model):
    shoe       = models.ForeignKey(ScrapedProduct, on_delete=models.CASCADE)
    collection = models.ForeignKey(Collection, on_delete=models.CASCADE)

    class Meta:
        unique_together = [("shoe", "collection")]
