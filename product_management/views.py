
from django.shortcuts import redirect, render
import shopify
from decouple import config

from .models import Store

def authenticate_shopify(request):

    SHOPIFY_SCOPES=['read_products','write_products','read_orders','write_orders','read_customers','write_customers']

    shopify.Session.setup(api_key=config('SHOPIFY_CLIENT_ID'), secret=config('SHOPIFY_CLIENT_SECRET'))
    session = shopify.Session(config('SHOPIFY_SHOP_URL'), config('SHOPIFY_API_VERSION'))
    auth_url = session.create_permission_url(SHOPIFY_SCOPES, config('SHOPIFY_REDIRECT_URI'))
    return redirect(auth_url)

def callback_shopify(request):
    # Extrai os parâmetros da query string
    params = request.GET
    
    if not all(params.values()):
        return render(request, 'error.html', {'error': 'Parâmetros ausentes na requisição.'})
    
    shopify.Session.setup(api_key=config('SHOPIFY_CLIENT_ID'), secret=config('SHOPIFY_CLIENT_SECRET'))

    session = shopify.Session(params.get('shop'), config('SHOPIFY_API_VERSION'))

    shopify.ShopifyResource.activate_session(session)


    try:
        shopify_token = session.request_token(params)  
        
        request.session['shopify_token'] = shopify_token

        store, created = Store.objects.get_or_create(shop_url=params.get('shop'))
        store.access_token = shopify_token

        # if store.location_id is None:
        #     store.location_id = create_shopify_location(shopify_token, params.get('shop'))
        store.save()
        
        return render(request, 'product_management/callback.html', {'shopify_token': shopify_token})
    except Exception as e:
        return render(request, 'error.html', {'error': str(e)})