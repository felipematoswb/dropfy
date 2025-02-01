# product_management/urls.py

from django.urls import path
from . import views

urlpatterns = [
    path('authenticate/', views.authenticate_shopify, name='authenticate_shopify'),
    path('callback/', views.callback_shopify, name='callback_shopify'),
]