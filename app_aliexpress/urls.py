""" url for app """
from django.urls import path

from . import views

urlpatterns = [
    path(
        "authorization/",
        views.authorization_aliexpress,
        name="authorization_aliexpress",
    ),
    path("callback/", views.callback_aliexpress, name="callback_aliexpress"),
    path("dashboard/", views.dashboard_aliexpress, name="dashboard_aliexpress"),
    path("feedname/", views.feedname_aliexpress, name="feedname_aliexpress"),
    path(
        "recommend_feed_aliexpress/<path:feed_name>/",
        views.recommend_feed_aliexpress,
        name="recommend_feed_aliexpress",
    ),
    path("product/<int:product_id>/", views.product_detail_aliexpress, \
        name="product_detail_aliexpress"),
    path(
        "text_search/",
        views.text_search_aliexpress,
        name="text_search_aliexpress",
    ),
    path(
        "image_search/",
        views.aliexpress_image_search,
        name="aliexpress_image_search",
    ),
]
