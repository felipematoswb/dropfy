
from django.db import models

class Product(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    aliexpress_id = models.CharField(max_length=100)
    shopify_id = models.CharField(max_length=100, blank=True, null=True)
    stock = models.IntegerField(default=0)

    def __str__(self):
        return self.title

class Order(models.Model):
    order_id = models.CharField(max_length=100)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.IntegerField()
    date_ordered = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Order {self.order_id}"
    
class Store(models.Model):
    shop_url = models.CharField(max_length=100)
    access_token = models.CharField(max_length=100)
    location_id = models.CharField(max_length=100, blank=True, null=True)
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    alter_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.shop_url