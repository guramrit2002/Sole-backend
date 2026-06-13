import re
import logging
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from scraper.models import ScrapedProduct
from scraper.services.pipeline import store_image
from .models import Collection
from .serializers import CollectionSerializer, CollectionWriteSerializer

logger = logging.getLogger(__name__)


def _needs_s3_backfill(shoe):
    return bool(
        shoe.image
        and (
            not shoe.image_s3
            or 'X-Amz-Signature=' in shoe.image_s3
            or 'AWSAccessKeyId=' in shoe.image_s3
        )
    )


def _backfill_collection_s3_images(coll):
    for shoe in coll.shoes.all():
        if not _needs_s3_backfill(shoe):
            continue
        try:
            shoe.image_s3 = store_image(shoe.image)
            shoe.save(update_fields=['image_s3', 'updated_at'])
        except Exception:
            logger.exception('S3 image backfill failed for shoe %s', shoe.pk)


def _sync_totals(coll):
    shoes = coll.shoes.all()
    total_shoes = shoes.count()
    total_worth = 0.0
    for s in shoes:
        if s.price:
            cleaned = re.sub(r'[^\d.]', '', str(s.price))
            try:
                total_worth += float(cleaned)
            except ValueError:
                pass
    coll.total_shoes = total_shoes
    coll.total_worth = round(total_worth, 2)
    coll.save(update_fields=['total_shoes', 'total_worth'])

class CollectionListCreateView(APIView):
    """
    GET  /api/collections/       — list the authenticated user's collections
    POST /api/collections/       — create a new collection
    Body: { "name": "...", "description": "...", "tags": ["tag1", "tag2"] }
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = Collection.objects.filter(user=request.user).\
            prefetch_related("shoes")
        return Response(CollectionSerializer(qs, many=True).data)

    def post(self, request):
        serializer = CollectionWriteSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, 
                            status=status.HTTP_400_BAD_REQUEST)
        collection = serializer.save(user=request.user)
        return Response(CollectionSerializer(collection).data, 
                        status=status.HTTP_201_CREATED)


class CollectionDetailView(APIView):
    """
    GET    /api/collections/<id>/  — retrieve a collection
    PATCH  /api/collections/<id>/  — update name / description / tags
    DELETE /api/collections/<id>/  — delete a collection
    """
    permission_classes = [IsAuthenticated]

    def _get(self, pk, user):
        try:
            return Collection.objects.get(pk=pk,user=user)
        except Collection.DoesNotExist:
            return None

    def get(self, request, pk):
        coll = self._get(pk, request.user)
        if not coll:
            return Response(status=status.HTTP_404_NOT_FOUND)
        _backfill_collection_s3_images(coll)
        total_shoes = coll.shoes.count()
        total_collections = coll.shoes.values("collections").distinct().count()
        return Response({**CollectionSerializer(coll).data, 
                         "total_shoes": total_shoes, 
                         "total_collections": total_collections})

    def patch(self, request, pk):
        coll = self._get(pk, request.user)
        if not coll:
            return Response(status=status.HTTP_404_NOT_FOUND)
        serializer = CollectionWriteSerializer(coll, data=request.data, 
                                               partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, 
                            status=status.HTTP_400_BAD_REQUEST)
        serializer.save()
        return Response(CollectionSerializer(coll).data)

    def delete(self, request, pk):
        coll = self._get(pk, request.user)
        if not coll:
            return Response(status=status.HTTP_404_NOT_FOUND)
        coll.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class CollectionShoeView(APIView):
    """
    POST   /api/collections/<id>/shoes/           — add a shoe  { "shoe_id": 5 }
    DELETE /api/collections/<id>/shoes/<shoe_id>/ — remove a shoe
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            coll = Collection.objects.get(pk=pk, user=request.user)
        except Collection.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        shoe_id = request.data.get("shoe_id")
        try:
            shoe = ScrapedProduct.objects.get(pk=shoe_id)
        except ScrapedProduct.DoesNotExist:
            return Response({"error": "shoe not found"},
                            status=status.HTTP_404_NOT_FOUND)
        if _needs_s3_backfill(shoe):
            try:
                shoe.image_s3 = store_image(shoe.image)
                shoe.save(update_fields=['image_s3', 'updated_at'])
            except Exception:
                logger.exception('S3 image backfill failed for shoe %s', shoe.pk)
        coll.shoes.add(shoe)
        _sync_totals(coll)
        return Response(CollectionSerializer(coll).data)

    def delete(self, request, pk, shoe_id):
        try:
            coll = Collection.objects.get(pk=pk, user=request.user)
        except Collection.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        try:
            shoe = ScrapedProduct.objects.get(pk=shoe_id)
        except ScrapedProduct.DoesNotExist:
            return Response({"error": "shoe not found"}, 
                            status=status.HTTP_404_NOT_FOUND)
        coll.shoes.remove(shoe)
        _sync_totals(coll)
        return Response(CollectionSerializer(coll).data)
