"""Module providing a function python version."""
import base64
from functools import wraps
import hashlib
import hmac
from io import BytesIO
import time
import json
import logging
from urllib.parse import quote, unquote
from pillow_avif import AvifImagePlugin
from PIL import Image  # Importe o plugin pillow-avif-plugin
import iop
import requests
from django.http import HttpResponseRedirect
from django.shortcuts import redirect, render
from django.core.paginator import EmptyPage, Paginator, PageNotAnInteger

from bs4 import BeautifulSoup
from decouple import config


logger = logging.getLogger(__name__)


APP_KEY = config("ALIEXPRESS_APP_KEY")
APP_SECRET = config("ALIEXPRESS_APP_SECRET")
APP_URL_REST = "https://api-sg.aliexpress.com/rest"
APP_URL_SYNC = "https://api-sg.aliexpress.com/sync"

ALIEXPRESS_TARGET_CURRENCY = "BRL"
ALIEXPRESS_SHIP_COUNTRY = "BR"
ALIEXPRESS_LOCALE = "pt_BR"


def process_product_description(html_content):
    """parser html aliexpress to app"""
    soup = BeautifulSoup(html_content, "html.parser")
    for img in soup.find_all("img"):
        if "width" in img.attrs:
            del img["width"]
        if "height" in img.attrs:
            del img["height"]
        img["style"] = "max-width: 100%; height: auto; display: block; margin: 10px 0;"
    return str(soup)


def reduce_image_size(image_file, max_size_kb=70, max_dimension=600):
    """
    Reduz o tamanho da imagem, converte para JPG e codifica em base64.
    """
    image = Image.open(image_file)
    output = BytesIO()

    valid_extensions = ['png', 'webp', 'jpg', 'jpeg', 'avif']
    file_extension = image.format.lower()
    if file_extension not in valid_extensions:
        raise ValueError(f"Formato de imagem inválido: {file_extension}")

    # Converte a imagem para RGB se necessário
    if file_extension not in ('jpeg', 'jpg', 'avif'):
        image = image.convert("RGB")

    # Redimensiona a imagem se necessário
    width, height = image.size
    if width > max_dimension or height > max_dimension:
        scaling_factor = min(max_dimension / width, max_dimension / height)
        new_width = int(width * scaling_factor)
        new_height = int(height * scaling_factor)
        image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)

    # Salva inicialmente para verificar o tamanho
    image.save(output, format='JPEG')
    initial_size_kb = output.tell() / 1024

    if initial_size_kb <= max_size_kb:
        output.seek(0)
        encoded_image = base64.b64encode(output.getvalue()).decode('utf-8')
        return encoded_image

    # Ajusta a qualidade para reduzir o tamanho do arquivo
    for quality in range(90, 10, -5):
        output.seek(0)
        output.truncate()
        image.save(output, format='JPEG', quality=quality)
        if output.tell() / 1024 <= max_size_kb:
            output.seek(0)
            encoded_image = base64.b64encode(output.getvalue()).decode('utf-8')
            return encoded_image

    # Redimensiona ainda mais se a redução de qualidade não for suficiente
    while output.tell() / 1024 > max_size_kb:
        width, height = image.size
        new_width = int(width * 0.9)
        new_height = int(height * 0.9)
        image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
        output.seek(0)
        output.truncate()
        image.save(output, format='JPEG', quality=quality)

    output.seek(0)
    encoded_image = base64.b64encode(output.getvalue()).decode('utf-8')
    return encoded_image

def generate_sign(secret, api_name, parameters):
    """Generate sign for Aliexpress API."""

    # URL encode parameters (Crucial for correct signing)
    encoded_parameters = {k: quote(str(v)) for k, v in parameters.items()}

    # Sort parameters
    sorted_params = sorted(encoded_parameters)

    # Build the parameter string using f-strings and handle api_name
    if "/" in api_name:
        parts = [f"{k}{encoded_parameters[k]}" for k in sorted_params]
        parameters_str = f"{api_name}{''.join(parts)}"
    else:
        parts = [f"{k}{encoded_parameters[k]}" for k in sorted_params]
        parameters_str = ''.join(parts)

    # Generate the sign using HMAC-SHA256
    h = hmac.new(
        secret.encode("utf-8"),  # Encoding is important!
        parameters_str.encode("utf-8"),  # Encoding must match!
        digestmod=hashlib.sha256,
    )
    return h.hexdigest().upper()


def token_required(view_func):
    """
    Decorator to check and refresh the access token.
    
    Args:
        view_func: The view function to decorate
    
    Returns:
        HttpResponse: The wrapped view response or redirect
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        expire_in = request.session.get("aliexpress_expire_in")

        if not expire_in:
            logger.warning("No expiration time set in session.")
            return redirect("/aliexpress/authorization/", {"error": "Authentication required."})

        current_time = int(time.time())
        if current_time + 60 >= expire_in:  # Check if token needs refresh
            try:
                refresh_response = refresh_aliexpress_token(request)
                # Improved type checking
                if not isinstance(refresh_response, HttpResponseRedirect):
                    logger.error("Refresh token function did not return a redirect.")
                    return redirect("/aliexpress/authorization/", \
                        {"error": "Token refresh failed."})
                return refresh_response

            except ValueError as ve:  # More specific exception
                logger.exception("ValueError during token refresh: %s", ve)
                return redirect(
                    "/aliexpress/authorization/",
                    {"error": "Token refresh failed. Please re-authenticate."}
                )

        return view_func(request, *args, **kwargs)

    return _wrapped_view


def authorization_aliexpress(request):
    """ token verification """
    # Verifica se o token de acesso está presente e válido
    # Falha ao renovar o token, redireciona para o fluxo de autorização
    redirect_uri = request.build_absolute_uri("/aliexpress/callback/")
    return redirect(
        f"https://api-sg.aliexpress.com/oauth/authorize?response_type=code \
            &force_auth=true&redirect_uri={redirect_uri}&client_id={APP_KEY}")



def callback_aliexpress(request):
    """Callback function using the iop library."""

    client = iop.IopClient(APP_URL_REST, APP_KEY, APP_SECRET)
    request_iop = iop.IopRequest('/auth/token/create')

    # Get the authorization code from the request
    code = request.GET.get("code")
    if not code:
        return redirect(
            "/aliexpress/authorization/",
            {"error": "Authorization code is missing."},
        )

    request_iop.add_api_param('code', code)

    try:
        response = client.execute(request_iop)

        # response.body is ALREADY a dictionary.  No need for json.loads()
        response_data = response.body  # Directly assign the dictionary

        if not all(
            key in response_data
            for key in ["access_token", "refresh_token", "expires_in"]
        ):
            logger.error("Incomplete or invalid API response.")
            return redirect(
                "/aliexpress/authorization/",
                {"error": "Incomplete or invalid API response."},
            )

        request.session["aliexpress_access_token"] = response_data.get("access_token")
        request.session["aliexpress_refresh_token"] = response_data.get("refresh_token")
        request.session["aliexpress_expire_in"] = int(time.time()) + int(
            response_data.get("expires_in")
        )

        return redirect("/aliexpress/dashboard/")

    except (KeyError, TypeError):  # Catch potential dictionary access errors
        logger.error("Error accessing data in API response.")
        return redirect(
            "/aliexpress/authorization/",
            {"error": "Error processing API response."},
        )



def refresh_aliexpress_token(request):
    """Refreshes the Aliexpress access token using the refresh token."""

    refresh_token = request.session.get("aliexpress_refresh_token")
    if not refresh_token:
        logger.error("No refresh token found in session.")
        return redirect("/aliexpress/authorization/", {"error": "No refresh token available."})


    client = iop.IopClient(APP_URL_REST, APP_KEY, APP_SECRET)
    request_iop = iop.IopRequest('/auth/token/refresh')
    request_iop.add_api_param('refresh_token', refresh_token)

    try:
        response = client.execute(request_iop)

        if response.type == "success":
            response_data = json.loads(response.body)

            if not all(
                key in response_data
                for key in ["access_token", "expires_in"]):
                logger.error("Incomplete or invalid refresh token API response.")

                return redirect("/aliexpress/authorization/", \
                    {"error": "Invalid refresh token. Please re-authorize."})
            request.session["aliexpress_access_token"] = response_data.get("access_token")
            # Update the expiration time
            request.session["aliexpress_expire_in"] = int(time.time()) \
                + int(response_data.get("expires_in"))

            # Refresh token may or may not be returned in the refresh response. Update if present.
            new_refresh_token = response_data.get("refresh_token")
            if new_refresh_token:
                request.session["aliexpress_refresh_token"] = new_refresh_token

            return redirect("/aliexpress/dashboard/")

        else:
            # Consider removing the old refresh token if the refresh fails
            # del request.session["aliexpress_refresh_token"]
            return redirect(
                "/aliexpress/authorization/",
                {"error": "Error refreshing access token. Please re-authorize."},
            )

    except json.JSONDecodeError:
        return redirect(
            "/aliexpress/authorization/",
            {"error": "Error decoding refresh token API response."},
        )

@token_required
def dashboard_aliexpress(request):
    """dashboard aliexpress"""
    return render(request, "app_aliexpress/aliexpress_dashboard.html")


def product_detail_aliexpress(request, product_id):
    """product detail aliexpress"""
    method = "aliexpress.ds.product.get"
    url_full = APP_URL_SYNC + method

    # Parâmetros da requisição
    params = {
        "app_key": APP_KEY,
        "timestamp": str(int(time.time() * 1000)),  # Timestamp em milissegundos
        "sign_method": "sha256",
        "method": method,
        "product_id": product_id,
        "target_currency": ALIEXPRESS_TARGET_CURRENCY,
        "ship_to_country": ALIEXPRESS_SHIP_COUNTRY,
        "access_token": request.session["aliexpress_access_token"],
    }

    # Gera o sign dinamicamente
    params["sign"] = generate_sign(APP_SECRET, method, params)

    # Cabeçalhos da requisição
    headers = {"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"}

    try:
        response = requests.post(
            url_full,
            data=params,
            headers=headers,
            timeout=10,
        )
        response.raise_for_status()

        # Decodificando a resposta JSON
        response_data = response.json()

        # Verifica se a resposta contém os dados esperados
        result = response_data.get("aliexpress_ds_product_get_response", {})
        if result:
            product = result.get("result", {})
        else:
            logger.error("Resposta da API inválida ou sem dados.")
            return render(
                request,
                "app_aliexpress/aliexpress_product_detail.html",
                {"error": "Erro ao obter dados da API."},
            )

    except requests.exceptions.RequestException:
        return render(
            request,
            "app_aliexpress/aliexpress_product_detail.html",
            {"error": "Erro interno ao processar a requisição."},
        )
    # Processar as URLs das imagens
    if (
        "ae_multimedia_info_dto" in product
        and "image_urls" in product["ae_multimedia_info_dto"]
    ):
        product["image_urls"] = product["ae_multimedia_info_dto"]["image_urls"].split(
            ";"
        )
    else:
        product["image_urls"] = []

    # Processe a descrição do produto
    processed_description = process_product_description(
        product["ae_item_base_info_dto"]["detail"]
    )
    product["ae_item_base_info_dto"]["detail"] = processed_description

    # processe o frete do produto
    freights = shipping_aliexpress(
        request.session["aliexpress_access_token"],
        product_id,
        sku_id=product["ae_item_sku_info_dtos"]["ae_item_sku_info_d_t_o"][0]["sku_id"],
    )
    return render(
        request,
        "app_aliexpress/aliexpress_product_detail.html",
        {"product": product, "freights": freights, "product_id": product_id},
    )

@token_required
def feedname_aliexpress(request):
    """Search feedname using AliExpress TOP API.
    
    Args:
        request: HTTP request object
    
    Returns:
        Rendered template with feedname data
    """
    context = {}
    promos = []
    # Check if refresh is requested
    refresh = request.GET.get("refresh") == "true" or request.method == "POST"

    if refresh or "promos" not in request.session:
        try:
            # Initialize TOP client
            client = iop.IopClient(APP_URL_SYNC, APP_KEY, APP_SECRET)
            # Create request
            request_api = iop.IopRequest('aliexpress.ds.feedname.get')
            # Add timestamp as API parameter (if required by your implementation)
            request_api.add_api_param('timestamp', str(int(time.time() * 1000)))
            # Execute request
            response = client.execute(request_api)
            # Process response
            if response.body.get('aliexpress_ds_feedname_get_response', {}).get('resp_result', {}) \
                .get('resp_code', {}) == 200:
                result = response.body.get('aliexpress_ds_feedname_get_response', {}) \
                               .get('resp_result', {}) \
                               .get('result', {})
                if result and "promos" in result and "promo" in result["promos"]:
                    promos = result["promos"]["promo"]
                    request.session["promos"] = promos
                else:
                    logger.error("Invalid API response structure: %s", response.body)
                    context["error"] = "Error retrieving API data"
            else:
                logger.error("API request failed: %s", response.body)
                context["error"] = "API request failed"


        except ValueError as ve:  # More specific exception
            logger.exception("ValueError during token refresh: %s", ve)
            return redirect(
                    "/aliexpress/dashboard/",
                    {"error": "Internal error processing request."}
            )
    else:
        # Use cached session data
        promos = request.session.get("promos", [])

    # Pagination
    paginator = Paginator(promos, 20)  # 10 items per page
    page_number = request.GET.get("page")

    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    context["page_obj"] = page_obj

    return render(request, "app_aliexpress/aliexpress_feedname.html", context)


def recommend_feed_aliexpress(request, feed_name):
    """Recommend feed from AliExpress using TOP API.

    Args:
        request: HTTP request object
        feed_name: Name of the feed to query

    Returns:
        Rendered template with recommended products or error message
    """

    page_no = int(request.GET.get("page", 1))
    page_size = 50

    try:
        # Initialize TOP client
        client = iop.IopClient(APP_URL_SYNC, APP_KEY, APP_SECRET)
        # Create and configure request
        request_api = iop.IopRequest('aliexpress.ds.recommend.feed.get')
        request_api.add_api_param('country', 'BR')
        request_api.add_api_param('target_currency', 'BRL')
        request_api.add_api_param('target_language', 'EN')
        request_api.add_api_param('page_size', str(page_size))
        request_api.add_api_param('sort', 'volumeDesc')
        request_api.add_api_param('page_no', str(page_no))
        request_api.add_api_param('feed_name', unquote(feed_name))
        request_api.add_api_param('timestamp', str(int(time.time() * 1000)))

        # Execute request
        response = client.execute(request_api)

        # Check if response is successful
        if response.body.get('aliexpress_ds_feedname_get_response', {}).get('resp_result', {}) \
                .get('resp_code', {}) == 200:  # Adjust based on actual success indicator
            error_message = response.body.get('error_message', 'Unknown API Error')
            logger.error("API error: %s", error_message)
            return render(
                request,
                "app_aliexpress/aliexpress_dashboard.html",
                {"error": error_message},
            )

        # Extract result from response
        api_result = response.body.get('aliexpress_ds_recommend_feed_get_response', {}) \
            .get('result', {})
        if not api_result:
            logger.error("Empty result in API response: %s", response.body)
            return render(
                request,
                "app_aliexpress/aliexpress_recommend_feed.html",
                {"error": "No results returned from API"},
            )

        products = api_result.get('products', {}).get('traffic_product_d_t_o', [])
        total_record_count = int(api_result.get('total_record_count', 0))
        is_finished = api_result.get('is_finished', False)

        # Calculate total pages
        total_pages = (total_record_count + page_size - 1) // page_size

        # Validate page number
        if page_no < 1 or page_no > total_pages:
            return render(
                request,
                "app_aliexpress/aliexpress_recommend_feed.html",
                {"error": f"Invalid page number. Valid range: 1 to {total_pages}"},
            )

        # Render successful response
        return render(
            request,
            "app_aliexpress/aliexpress_recommend_feed.html",
            {
                "products": products,
                "feed_name": feed_name,
                "current_page": page_no,
                "total_results": total_record_count,
                "total_pages": total_pages,
                "is_finished": is_finished,
            },
        )

    except ValueError as ve:  # More specific exception
        logger.exception("ValueError during token refresh: %s", ve)
        return redirect(
                "/aliexpress/dashboard/",
                {"error": "Internal error processing request."}
        )


def shipping_aliexpress(access_token, product_id, sku_id):
    """Calculate shipping for a product using AliExpress TOP API.

    Args:
        access_token (str): Authentication token
        product_id (str): Product identifier
        sku_id (str): SKU identifier

    Returns:
        dict: Shipping information or error details
    """

    # Prepare query delivery request
    query_delivery_req = {
        "productId": product_id,
        "selectedSkuId": sku_id,
        "currency": ALIEXPRESS_TARGET_CURRENCY,
        "shipToCountry": ALIEXPRESS_SHIP_COUNTRY,
        "quantity": 1,
        "language": ALIEXPRESS_LOCALE,
        "locale": "zh_CN",
    }

    try:
        # Initialize TOP client
        client = iop.IopClient(APP_URL_SYNC, APP_KEY, APP_SECRET)
        # Create and configure request
        request = iop.IopRequest('aliexpress.ds.freight.query')
        request.add_api_param('queryDeliveryReq', json.dumps(query_delivery_req))
        request.add_api_param('timestamp', str(int(time.time() * 1000)))

        # Execute request with access token
        response = client.execute(request, access_token)

        # Check response
        if response.body.get('aliexpress_ds_freight_query_response', {}).get('result', {}) \
                .get('code', {}) != 200:  # Adjust based on actual success indicator
            error_msg = response.body.get('error_message', 'Unknown API Error')
            logger.error("API error: %s", error_msg)
            return {"error": error_msg}

        # Extract result
        result = response.body.get('aliexpress_ds_freight_query_response', {}).get('result', {}) \
            .get('delivery_options', {}).get('delivery_option_d_t_o', {})
        if result:
            return result
        else:
            logger.error("Invalid or empty API response: %s", response.body)
            return {"error": "Error retrieving API data"}

    except ValueError as ve:  # More specific exception
        logger.exception("ValueError during token refresh: %s", ve)
        return redirect(
                "/aliexpress/dashboard/",
                {"error": "Internal error processing request."}
        )


def text_search_aliexpress(request):
    """Search products by text using AliExpress TOP API.

    Args:
        request: HTTP request object

    Returns:
        Rendered template with search results or error message
    """

    keyword = request.GET.get('keyword', '')
    page_index = request.GET.get('page', '1')
    page_size = '20'  # Default page size
    current_page = int(request.GET.get('page', 1))


    try:
        # Initialize TOP client
        client = iop.IopClient(APP_URL_SYNC, APP_KEY, APP_SECRET)
        # Create and configure request
        request_api = iop.IopRequest('aliexpress.ds.text.search')
        request_api.add_api_param('keyWord', keyword)
        request_api.add_api_param('local', 'zh_CN')
        request_api.add_api_param('countryCode', 'US')
        request_api.add_api_param('sortBy', 'min_price')
        request_api.add_api_param('pageSize', page_size)
        request_api.add_api_param('pageIndex', page_index)
        request_api.add_api_param('currency', 'USD')
        request_api.add_api_param('timestamp', str(int(time.time() * 1000)))

        # Execute request
        response = client.execute(request_api, request.session["aliexpress_access_token"])

        if response.body.get('aliexpress_ds_text_search_response', {}).get('data', {}) \
            .get('products', {}) is None:  # Adjust based on actual success indicator
            error_message = response.body.get('error_message', 'Unknown API Error')
            logger.error("API error: %s", error_message)
            return render(
                request,
                "app_aliexpress/aliexpress_text_search.html",
                {"error": error_message}
            )

        # Process response
        result = response.body.get('aliexpress_ds_text_search_response', {}).get('data', {})
        products = result.get('products', {}).get('selection_search_product', [])
        total_count = result.get('totalCount', 0)  # Adjust based on actual field name
        total_pages = (int(total_count) + int(page_size) - 1) // int(page_size)
        is_finished = current_page >= total_pages


        context = {
            'products': products,
            'keyword': keyword,
            'current_page': current_page,
            'total_pages': total_pages,
            'is_finished': is_finished,
            'total_results': total_count,
        }

        return render(request, "app_aliexpress/aliexpress_text_search.html", context)
    except ValueError as ve:  # More specific exception
        logger.exception("ValueError during token refresh: %s", ve)
        return redirect(
                "/aliexpress/dashboard/",
                {"error": "Internal error processing request."}
        )



@token_required
def aliexpress_image_search(request):
    """View to perform Aliexpress image search."""

    # Get image_base64 from the request (you'll need to handle how this is sent)
    if request.method == "POST" and 'image_file' in request.FILES:
        image_file = request.FILES['image_file']
        if not image_file:
            return render(request, "app_aliexpress/aliexpress_image_search.html", \
                {"error": "Please provide an image."})

        try:
            # Reduce the image size
            reduced_image = reduce_image_size(image_file)
            client = iop.IopClient(APP_URL_SYNC, APP_KEY, APP_SECRET)
            request_api = iop.IopRequest('aliexpress.ds.image.searchV2')

            # Construct the param0 JSON
            params = {
                "sort_type": "price",
                "image_base64": reduced_image,
                "lang": "en",
                "sort_order": "asc",
                "ship_to": "BR"
            }
            request_api.add_api_param('param0', json.dumps(params))  # Convert to JSON string

            access_token = request.session.get("aliexpress_access_token")
            response = client.execute(request_api, access_token)
            if response.body.get("aliexpress_ds_image_searchV2_response", {}) \
                .get("result", {}).get("data", {}).get("data", []):
                context = {
                    "products": response.body.get("aliexpress_ds_image_searchV2_response", {}) \
                    .get("result", {}).get("data", {}).get("data", [])
                }
                return render(request, "app_aliexpress/aliexpress_image_search.html", \
                    context)
            else:
                return render(request, "app_aliexpress/aliexpress_image_search.html", \
                    {"error": "Image search none."})

        except ValueError as ve:  # More specific exception
            logger.exception("ValueError during token refresh: %s", ve)
            return redirect(
                    "/aliexpress/dashboard/",
                    {"error": "Internal error processing request."}
            )
    else:
        return render(request, "app_aliexpress/aliexpress_image_search.html", {"results": ""})
        