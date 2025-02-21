"""Module providing a function python version."""
import hashlib
import hmac
import functools
import time
import json
import logging
from urllib.parse import unquote
import requests
from bs4 import BeautifulSoup
from decouple import config
from django.shortcuts import redirect, render
from django.core.paginator import EmptyPage, Paginator, PageNotAnInteger


logger = logging.getLogger(__name__)


APP_KEY = config("ALIEXPRESS_APP_KEY")
APP_SECRET = config("ALIEXPRESS_APP_SECRET")
APP_URL_REST = "https://api-sg.aliexpress.com/rest"
APP_URL_SYNC = "https://api-sg.aliexpress.com/sync"

ALIEXPRESS_TARGET_CURRENCY = "BRL"
ALIEXPRESS_SHIP_COUNTRY = "BR"
ALIEXPRESS_LOCALE = "pt_BR"


def token_required(view_func):
    """ look for token """
    @functools.wraps(view_func)
    def wrapper(request, *args, **kwargs):
        # Verifica se o token de acesso está presente na sessão
        access_token = request.session.get("aliexpress_access_token")
        expire_in = request.session.get("aliexpress_expire_in", 0)

        # Se o token estiver expirado ou não existir, renova o token
        if not access_token or expire_in < int(time.time()):
            refresh_result = refresh_aliexpress(request)
            if "error" in refresh_result:
                # Se houver erro ao renovar o token, retorna o erro
                return render(request, "error.html", {"error": refresh_result["error"]})

        # Chama a função original
        return view_func(request, *args, **kwargs)

    return wrapper


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


def generate_sign(secret, api_name, parameters):
    """ generate sign aliexpress api page """
    # Ordena os parâmetros
    sorted_params = sorted(parameters)
    if "/" in api_name:
        parameters_str = "%s%s" % (
            api_name,
            str().join("%s%s" % (key, parameters[key]) for key in sorted_params),
        )
    else:
        parameters_str = str().join(
            "%s%s" % (key, parameters[key]) for key in sorted_params
        )

    # Gera o sign usando HMAC-SHA256
    h = hmac.new(
        secret.encode(encoding="utf-8"),
        parameters_str.encode(encoding="utf-8"),
        digestmod=hashlib.sha256,
    )
    return h.hexdigest().upper()


def authorization_aliexpress(request):
    """ token verification """
    # Verifica se o token de acesso está presente e válido
    access_token = request.session.get("aliexpress_access_token")
    expire_in = request.session.get("aliexpress_expire_in", 0)

    if access_token and int(time.time()) < expire_in:
        # Token ainda válido
        return redirect("/aliexpress/dashboard/", {"message": "Token ainda válido."})

    # Token expirado ou ausente, tenta renovar
    refresh_result = refresh_aliexpress(request)
    if "success" in refresh_result:
        # Token renovado com sucesso
        return redirect(
            "/aliexpress/dashboard/", {"message": refresh_result["message"]}
        )
    else:
        # Falha ao renovar o token, redireciona para o fluxo de autorização
        redirect_uri = request.build_absolute_uri("/aliexpress/callback/")
        return redirect(
            f"https://api-sg.aliexpress.com/oauth/authorize?response_type=code \
                &force_auth=true&redirect_uri={redirect_uri}&client_id={APP_KEY}")


def callback_aliexpress(request):
    """ callback function """
    method = "/auth/token/create"
    url_full = APP_URL_REST + method

    # Parâmetros da requisição
    params = {
        "app_key": APP_KEY,
        "timestamp": str(int(time.time() * 1000)),  # Timestamp em milissegundos
        "sign_method": "sha256",
        "code": request.GET.get("code"),
    }

    params["sign"] = generate_sign(APP_SECRET, method, params)

    # Cabeçalhos da requisição
    headers = {"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"}

    try:
        # Fazendo a requisição POST
        response = requests.post(
            url_full,
            data=params,
            headers=headers,
            timeout=10
        )
        response.raise_for_status()

        # Decodificando a resposta JSON
        response_data = response.json()

        # Verifica se a resposta contém os campos esperados
        if not all(
            key in response_data
            for key in ["access_token", "refresh_token", "expires_in"]
        ):
            logger.error("Resposta da API incompleta ou inválida.")
            return redirect(
                "/aliexpress/authorization/",
                {"error": "Resposta da API incompleta ou inválida."},
            )

        # Armazenando os tokens na sessão
        request.session["aliexpress_access_token"] = response_data.get("access_token")
        request.session["aliexpress_refresh_token"] = response_data.get("refresh_token")
        request.session["aliexpress_expire_in"] = int(time.time()) + int(
            response_data.get("expires_in")
        )

    except json.JSONDecodeError:
        return redirect(
            "/aliexpress/authorization/",
            {"error": "Erro ao decodificar a resposta da API."},
        )

    except requests.exceptions.RequestException:
        return redirect(
            "/aliexpress/authorization/",
            {"error": "Erro ao tentar obter tokens de acesso."},
        )

    return redirect("/aliexpress/dashboard/")


def refresh_aliexpress(request):
    """ refresh token  """
    refresh_token = request.session.get("aliexpress_refresh_token")
    if not refresh_token:
        return {"error": "Refresh token não encontrado na sessão."}

    method = "/auth/token/refresh"
    url_full = APP_URL_REST + method

    # Parâmetros da requisição
    params = {
        "app_key": APP_KEY,
        "timestamp": str(int(time.time() * 1000)),  # Timestamp em milissegundos
        "sign_method": "sha256",
        "refresh_token": refresh_token,
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

        # Verifica se a resposta contém os campos esperados
        if not all(
            key in response_data
            for key in ["access_token", "refresh_token", "expires_in"]
        ):
            error_message = response_data.get(
                "message", "Resposta da API incompleta ou inválida."
            )
            return {"error": error_message}

        # Atualiza os tokens na sessão
        request.session["aliexpress_access_token"] = response_data.get("access_token")
        request.session["aliexpress_refresh_token"] = response_data.get("refresh_token")
        request.session["aliexpress_expire_in"] = int(time.time()) + int(
            response_data.get("expires_in")
        )

        return {"success": True, "message": "Token renovado com sucesso."}

    except json.JSONDecodeError as e:
        return {"error": f"Erro ao decodificar a resposta da API: {str(e)}"}

    except requests.exceptions.RequestException as e:
        # Verifica se o erro é devido a um refresh token inválido ou expirado
        if "invalid or expired" in str(e).lower():
            return {
                "error": "The specified refresh token is invalid or expired. Redirecionando \
                    para autorização..."
            }
        return {"error": f"Erro ao tentar renovar o token: {str(e)}"}


@token_required
def dashboard_aliexpress(request):
    """dashboard aliexpress"""
    return render(request, "app_aliexpress/aliexpress_dashboard.html")


@token_required
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


def feedname_aliexpress(request):
    """ search feedname """
    context = {}
    promos = []
    # Verifica se o usuário solicitou uma atualização
    refresh = request.GET.get("refresh") == "true" or request.method == "POST"

    if refresh or "promos" not in request.session:
        # Faz uma nova requisição à API para atualizar os dados
        method = "aliexpress.ds.feedname.get"
        url_full = APP_URL_SYNC + method

        # Parâmetros da requisição
        params = {
            "app_key": APP_KEY,
            "timestamp": str(int(time.time() * 1000)),  # Timestamp em milissegundos
            "sign_method": "sha256",
            "method": method,
        }

        # Gera o sign dinamicamente
        params["sign"] = generate_sign(APP_SECRET, method, params)

        # Cabeçalhos da requisição
        headers = {"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"}

        try:

            response = requests.post(url_full, data=params, headers=headers, timeout=10)
            response.raise_for_status()

            # Decodificando a resposta JSON
            response_data = response.json()

            # Verifica se a resposta contém os dados esperados
            result = (
                response_data.get("aliexpress_ds_feedname_get_response", {})
                .get("resp_result", {})
                .get("result", {})
            )

            if result and "promos" in result and "promo" in result["promos"]:
                promos = result["promos"]["promo"]
                request.session["promos"] = promos  # Salva os dados na sessão
            else:
                logger.error("Resposta da API inválida ou sem dados.")
                context["error"] = "Erro ao obter dados da API."

        except requests.exceptions.RequestException:

            context["error"] = "Erro interno ao processar a requisição."
    else:
        # Usa os dados da sessão
        promos = request.session["promos"]

    # Paginação
    paginator = Paginator(promos, 10)  # 10 itens por página
    page_number = request.GET.get("page")

    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)  # Página inicial se o número não for inteiro
    except EmptyPage:
        page_obj = paginator.page(
            paginator.num_pages
        )  # Última página se o número for inválido

    context["page_obj"] = page_obj

    return render(request, "app_aliexpress/aliexpress_feedname.html", context)


def recommend_feed_aliexpress(request, feed_name):
    """recommend feed aliexpress."""

    method = "aliexpress.ds.recommend.feed.get"
    url_full = APP_URL_SYNC + "/" + method

    page_no = int(request.GET.get("page", 1))  # Current page number from request
    page_size = 50  # Products per page

    params = {
        "app_key": APP_KEY,
        "method": method,
        "timestamp": str(int(time.time() * 1000)),
        "sign_method": "sha256",
        "country": "BR",
        "target_currency": "BRL",
        "target_language": "EN",
        "page_size": page_size,
        "sort": "volumeDesc",
        "page_no": page_no,
        "feed_name": unquote(feed_name),
    }

    params["sign"] = generate_sign(APP_SECRET, method, params)
    headers = {"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"}

    try:
        response = requests.post(url_full, data=params, headers=headers, timeout=10)
        response.raise_for_status()
        response_data = response.json()

        api_result = response_data.get(
            "aliexpress_ds_recommend_feed_get_response", {}
        ).get("result")
        if not api_result:
            error_message = response_data.get(
                "aliexpress_ds_recommend_feed_get_response", {}
            ).get("error_message", "Unknown API Error")
            return render(
                request,
                "app_aliexpress/aliexpress_recommend_feed.html",
                {"error": error_message},
            )

        products = api_result.get("products", {}).get("traffic_product_d_t_o", [])
        total_record_count = int(
            api_result.get("total_record_count", 0)
        )  # Total products available
        is_finished = api_result.get(
            "is_finished", False
        )  # Whether there are more pages

        # Calculate total pages
        total_pages = (total_record_count + page_size - 1) // page_size

        # Validate page_no
        if page_no < 1 or page_no > total_pages:
            return render(
                request,
                "app_aliexpress/aliexpress_recommend_feed.html",
                {"error": f"Invalid page number. Valid range: 1 to {total_pages}."},
            )

        return render(
            request,
            "app_aliexpress/aliexpress_recommend_feed.html",
            {
                "products": products,
                "feed_name": feed_name,
                "current_page": page_no,
                "total_results": total_record_count,
                "total_pages": total_pages,  # Pass total_pages to the template
                "is_finished": is_finished,  # Pass is_finished to the template
            },
        )

    except requests.exceptions.RequestException:
        return render(
            request,
            "app_aliexpress/aliexpress_recommend_feed.html",
            {"error": "Error loading products. Please try again later."},
        )


def shipping_aliexpress(access_token, product_id, sku_id):
    """ calculate shiiping product """
    method = "aliexpress.ds.freight.query"
    url_full = APP_URL_SYNC + method

    query_delivery_req = {
        "productId": product_id,
        "selectedSkuId": sku_id,
        "currency": ALIEXPRESS_TARGET_CURRENCY,
        "shipToCountry": ALIEXPRESS_SHIP_COUNTRY,
        "quantity": 1,
        "language": ALIEXPRESS_LOCALE,
        "locale": "zh_CN",
    }
    # Parâmetros da requisição
    params = {
        "app_key": APP_KEY,
        "timestamp": str(int(time.time() * 1000)),  # Timestamp em milissegundos
        "sign_method": "sha256",
        "method": method,
        "access_token": access_token,
        "queryDeliveryReq": json.dumps(query_delivery_req),
    }

    # Gera o sign dinamicamente
    params["sign"] = generate_sign(APP_SECRET, method, params)

    # Cabeçalhos da requisição
    headers = {"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"}

    try:
        response = requests.post(url_full, data=params, headers=headers, timeout=10)
        response.raise_for_status()

        # Decodificando a resposta JSON
        response_data = response.json()

        # Verifica se a resposta contém os dados esperados
        result = response_data.get("aliexpress_ds_freight_query_response", {}).get(
            "result", {}
        )
        if result:
            return result
        else:
            logger.error("Resposta da API inválida ou sem dados.")
            return {"error": "Erro ao obter dados da API."}

    except requests.exceptions.RequestException:
        return {"error": "Erro interno ao processar a requisição."}
