import json
from django.shortcuts import get_object_or_404, redirect, render
import shopify
from decouple import config

from .models import Store


def install_shopify(request):
    return render(request, "app_shopify/install.html")


def authenticate_shopify(request):

    SHOP_URL = request.POST.get("shop")
    if not SHOP_URL:
        return render(request, "error.html", {"error": "Parâmetro shop não informado."})

    SHOPIFY_SCOPES = [
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
    session = shopify.Session(SHOP_URL, config("SHOPIFY_API_VERSION"))
    auth_url = session.create_permission_url(
        SHOPIFY_SCOPES, config("SHOPIFY_REDIRECT_URI")
    )

    return redirect(auth_url)


def callback_shopify(request):

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

        store, created = Store.objects.get_or_create(shop_url=params.get("shop"))
        store.access_token = shopify_token

        # if store.location_id is None:
        #     store.location_id = create_shopify_location(shopify_token, params.get('shop'))
        store.save()

        return redirect("/shopify/dashboard/")
    except Exception as e:
        return render(request, "error.html", {"error": str(e)})


def dashboard_shopify(request):
    stores = Store.objects.all()

    return render(request, "app_shopify/dashboard.html", {"stores": stores})


def activate_store_shopify(request, store_id):
    Store.objects.all().update(is_active=False)
    store = get_object_or_404(Store, id=store_id)
    store.is_active = True
    store.save()
    return redirect("/shopify/dashboard/")


def remove_store_shopify(request, store_id):
    store = get_object_or_404(Store, id=store_id)
    store.delete()
    return redirect("/shopify/dashboard/")


def list_products_shopify(request, store_id):
    store = Store.objects.get(id=store_id)

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
    except Exception as e:
        return render(request, "error.html", {"error": str(e)})
    finally:
        # Desativa a sessão da Shopify
        shopify.ShopifyResource.clear_session()


def push_product_shopify(request, product_id):

    return render(request, "app_shopify/shopify_push_product.html")
