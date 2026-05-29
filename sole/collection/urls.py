from django.urls import path
from .views import CollectionListCreateView, CollectionDetailView, CollectionShoeView

urlpatterns = [
    path("",                                    CollectionListCreateView.as_view(), name="collections"),
    path("<int:pk>/",                           CollectionDetailView.as_view(),     name="collection-detail"),
    path("<int:pk>/shoes/",                     CollectionShoeView.as_view(),       name="collection-shoes"),
    path("<int:pk>/shoes/<int:shoe_id>/",       CollectionShoeView.as_view(),       name="collection-shoe-detail"),
]
