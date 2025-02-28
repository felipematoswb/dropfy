""" added url shopify"""

from django.urls import path
from . import views

urlpatterns = [
    path("install/", views.install_shopify, name="install_shopify"),
    path("authenticate/", views.authenticate_shopify, name="authenticate_shopify"),
    path("callback/", views.callback_shopify, name="callback_shopify"),
    path("dashboard/", views.dashboard_shopify, name="dashboard_shopify"),
    path(
        "activate/<int:store_id>/",
        views.activate_store_shopify,
        name="activate_store_shopify",
    ),
    path(
        "remove/<int:store_id>/",
        views.remove_store_shopify,
        name="remove_store_shopify",
    ),
    path(
        "products/<int:store_id>/",
        views.list_products_shopify,
        name="list_products_shopify",
    ),
    path(
        "push/<int:product_id>/",
        views.push_product_shopify,
        name="push_product_shopify",
    ),
]
