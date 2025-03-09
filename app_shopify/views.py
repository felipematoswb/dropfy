"""modules to  shopiffy views"""
import json
from venv import logger
from django.shortcuts import get_object_or_404, redirect, render
import shopify
from decouple import config

from app_aliexpress.views import fetch_aliexpress_product_detail

from .models import Product, ShopStore

def install_shopify(request):
    """

    Args:
        request (_type_): _description_

    Returns:
        _type_: _description_
    """
    return render(request, "app_shopify/install.html")

def authenticate_shopify(request):
    """

    Args:
        request (_type_): _description_

    Returns:
        _type_: _description_
    """

    shop_url = request.POST.get("shop")
    if not shop_url:
        return render(request, "error.html", {"error": "Parâmetro shop não informado."})

    shopify_scopes = [
        "read_products",
        "write_products",
        "read_orders",
        "write_orders",
        "read_customers",
        "write_customers",
    ]

    shopify.Session.setup(
        api_key=config("SHOPIFY_CLIENT_ID"), secret=config("SHOPIFY_CLIENT_SECRET")
    )
    session = shopify.Session(shop_url, config("SHOPIFY_API_VERSION"))
    auth_url = session.create_permission_url(
        shopify_scopes, config("SHOPIFY_REDIRECT_URI")
    )

    return redirect(auth_url)

def callback_shopify(request):
    """

    Args:
        request (_type_): _description_

    Returns:
        _type_: _description_
    """

    params = request.GET

    if not all(params.values()):
        return render(
            request, "error.html", {"error": "Parâmetros ausentes na requisição."}
        )

    shopify.Session.setup(
        api_key=config("SHOPIFY_CLIENT_ID"), secret=config("SHOPIFY_CLIENT_SECRET")
    )

    session = shopify.Session(params.get("shop"), config("SHOPIFY_API_VERSION"))

    shopify.ShopifyResource.activate_session(session)

    try:
        shopify_token = session.request_token(params)

        request.session["shopify_token"] = shopify_token

        store, created = ShopStore.objects.get_or_create(shop_url=params.get('shop')) # pylint: disable=E1101, W0612
        store.access_token = shopify_token

        # if store.location_id is None:
        #     store.location_id = create_shopify_location(shopify_token, params.get('shop'))
        store.save()

        return redirect("/shopify/dashboard/")
    except ValueError as ve:  # More specific exception
        logger.exception("ValueError during token refresh: %s", ve)
        return redirect("/aliexpress/dashboard/",
                    {"error": "Internal error processing request."})

def dashboard_shopify(request):
    """

    Args:
        request (_type_): _description_

    Returns:
        _type_: _description_
    """
    stores = ShopStore.objects.all() # pylint: disable=E1101

    return render(request, "app_shopify/dashboard.html", {"stores": stores})

def activate_store_shopify(store_id):
    """

    Args:
        request (_type_): _description_

    Returns:
        _type_: _description_
    """
    ShopStore.objects.all().update(is_active=False) # pylint: disable=E1101
    store = get_object_or_404(ShopStore, id=store_id)
    store.is_active = True
    store.save()
    return redirect("/shopify/dashboard/")

def remove_store_shopify(store_id):
    """

    Args:
        request (_type_): _description_

    Returns:
        _type_: _description_
    """
    store = get_object_or_404(ShopStore, id=store_id)
    store.delete()
    return redirect("/shopify/dashboard/")

def list_products_shopify(request, store_id):
    """

    Args:
        request (_type_): _description_

    Returns:
        _type_: _description_
    """
    store = ShopStore.objects.get(id=store_id) # pylint: disable=E1101

    if not store:
        return render(
            request, "error.html", {"error": "Nenhuma loja ativa encontrada."}
        )

    shopify.Session.setup(
        api_key=config("SHOPIFY_CLIENT_ID"), secret=config("SHOPIFY_CLIENT_SECRET")
    )
    session = shopify.Session(store.shop_url, config("SHOPIFY_API_VERSION"))
    session.token = store.access_token
    shopify.ShopifyResource.activate_session(session)

    try:
        # Consulta GraphQL para buscar produtos
        query = """
        {
            products(first: 10) {
                edges {
                    node {
                        id
                        title
                        descriptionHtml
                        variants(first: 1) {
                            edges {
                                node {
                                    price
                                    inventoryQuantity
                                }
                            }
                        }
                        status
                    }
                }
            }
        }
        """
        result = json.loads(shopify.GraphQL().execute(query))
        products = result["data"]["products"]["edges"]

        # Formata os produtos para o template
        formatted_products = []
        for edge in products:
            product = edge["node"]
            formatted_products.append(
                {
                    "id": product["id"],
                    "title": product["title"],
                    "description": product["descriptionHtml"],
                    "price": product["variants"]["edges"][0]["node"]["price"],
                    "status": product["status"],
                }
            )

        return render(
            request, "app_shopify/list_products.html", {"products": formatted_products}
        )
    except ValueError as ve:  # More specific exception
        logger.exception("ValueError during token refresh: %s", ve)
        return redirect("/aliexpress/dashboard/",
                    {"error": "Internal error processing request."})
    finally:
        # Desativa a sessão da Shopify
        shopify.ShopifyResource.clear_session()

def push_product_shopify(request, product_id):
    """

    Args:
        request (_type_): _description_

    Returns:
        _type_: _description_
    """
    if request.method == 'GET':
        try:
            access_token = request.session.get("aliexpress_access_token")
            if not access_token:
                return redirect("/aliexpress/dashboard/", {"error": "Access token missing."})

            product, freights_or_error = fetch_aliexpress_product_detail(access_token, product_id)

            if isinstance(freights_or_error,str):
                return redirect("/aliexpress/dashboard/", {"error": freights_or_error})

            if product is None:
                return redirect("/aliexpress/dashboard/", {"error": "Failed to retrieve \
                    product details."})
            return render(
                request,
                "app_shopify/shopify_push_product.html",
                {"product": product, "freights": freights_or_error, "product_id": product_id},
            )
        except ValueError as ve:  # More specific exception
            logger.exception("ValueError during token refresh: %s", ve)
            return redirect("/aliexpress/dashboard/", {"error": "Internal error \
                processing request."})
    if request.method == 'POST':
        print(request.POST)
        try:
            store = ShopStore.objects.get(is_active=True) # pylint: disable=E1101
            if not store:
                return redirect("/shopify/dashboard/", {"error": "No active store found."})

            shopify.Session.setup(
                api_key=config("SHOPIFY_CLIENT_ID"), secret=config("SHOPIFY_CLIENT_SECRET")
            )
            session = shopify.Session(store.shop_url, config("SHOPIFY_API_VERSION"))
            session.token = store.access_token
            shopify.ShopifyResource.activate_session(session)

            product = Product.objects.get(aliexpress_id=product_id) # pylint: disable=E1101

            # Create a new Shopify product
            new_product = shopify.Product()
            new_product.title = product.title
            new_product.body_html = product.description
            new_product.vendor = "AliExpress"
            new_product.product_type = "AliExpress Product"
            new_product.save()

            # Create a new Shopify variant
            new_variant = shopify.Variant()
            new_variant.product_id = new_product.id
            new_variant.price = product.price
            new_variant.inventory_quantity = product.stock
            new_variant.save()

            # Associate the Shopify product with the Shopify store
            store.shopify_id = new_product.id
            store.save()

            return redirect("/shopify/dashboard/")
        except ValueError as ve:  # More specific exception
            logger.exception("ValueError during token refresh: %s", ve)
            return redirect("/aliexpress/dashboard/", {"error": "Internal error \
                processing request."})
        finally:
            # Desativa a sessão da Shopify
            shopify.ShopifyResource.clear_session()
