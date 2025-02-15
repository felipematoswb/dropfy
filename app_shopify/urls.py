
from django.urls import path
from . import views

urlpatterns = [
    path('install/', views.install_shopify, name='install_shopify'),
    path('authenticate/', views.authenticate_shopify, name='authenticate_shopify'),
    path('callback/', views.callback_shopify, name='callback_shopify'),
    path('dashboard/', views.shopify_dashboard, name='shopify_dashboard'),
    path('activate/<int:store_id>/', views.activate_store, name='activate_store'),
    path('remove/<int:store_id>/', views.remove_store, name='remove_store'),
]