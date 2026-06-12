import logging
from urllib.parse import urlparse

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import ScrapedProduct
from .serializers import (
    ScrapeRequestSerializer, ScrapedProductSerializer,
)
from .services.pipeline import run, store_image

logger = logging.getLogger(__name__)


def _store_s3_image_url(image_url: str) -> str:
    try:
        return store_image(image_url)
    except Exception:
        logger.exception("S3 image upload failed for %s", image_url)
        raise


class ScrapeView(APIView):
    """
    POST /api/scrape/
    Body : { "url": "https://...", "force": false }

    Runs the layered pipeline (curl-cffi → Scrapling → Playwright).
    Cached if already scraped unless force=true.
    """
    
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ScrapeRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, 
                            status=status.HTTP_400_BAD_REQUEST)

        url      = serializer.validated_data["url"]
        force    = serializer.validated_data["force"]
        url_hash = ScrapedProduct.make_hash(url)

        if not force:
            try:
                cached = ScrapedProduct.objects.get(url_hash=url_hash)
                if cached.image and not cached.image_s3:
                    try:
                        cached.image_s3 = _store_s3_image_url(cached.image)
                        cached.save(update_fields=["image_s3", "updated_at"])
                    except Exception as exc:
                        return Response(
                            {"error": "image upload failed", "detail": str(exc)},
                            status=status.HTTP_502_BAD_GATEWAY,
                        )
                data   = ScrapedProductSerializer(cached).data
                data["cached"] = True
                return Response(data, status=status.HTTP_200_OK)
            except ScrapedProduct.DoesNotExist:
                pass

        logger.info("scraping %s", url)
        try:
            result = run(url)
        except Exception as exc:
            logger.exception("pipeline error for %s", url)
            return Response(
                {"error": "pipeline failed", "detail": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        if result is None:
            return Response(
                {"error": "all layers exhausted — no data extracted", 
                 "url": url},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        source = urlparse(url).netloc.replace("www.", "")
        image_s3 = None

        if result.image:
            try:
                image_s3 = _store_s3_image_url(result.image)
            except Exception as exc:
                return Response(
                    {"error": "image upload failed", "detail": str(exc)},
                    status=status.HTTP_502_BAD_GATEWAY,
                )

        product, _ = ScrapedProduct.objects.update_or_create(
            url_hash=url_hash,
            defaults=dict(
                url        = url,
                name       = result.name,
                price      = result.price,
                currency   = result.currency,
                image      = result.image,
                image_s3   = image_s3,
                source     = source,
                layer_used = result.source_layer,
                is_complete= result.is_complete(),
                confidence = result.filled() / 3.0,
            ),
        )

        data           = ScrapedProductSerializer(product).data
        data["cached"] = False
        return Response(data, status=status.HTTP_201_CREATED)
