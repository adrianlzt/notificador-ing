#! /usr/bin/env python
# -*- coding: utf-8 -*-
# vim:fenc=utf-8
#
# Copyright © 2016 Adrián López Tejedor <adrianlzt@gmail.com>
#
# Distributed under terms of the GNU GPLv3 license.

"""

"""
from bottle import Bottle, request, static_file, run, debug
from jinja2 import Template,Environment,FileSystemLoader

from chequea_imagenes import parse_pin
import pushbullet
from config import Config

from datetime import date,timedelta,datetime
from PIL import Image
from StringIO import StringIO
from base64 import b64decode
from threading import Timer
from bs4 import BeautifulSoup

import time
import requests
import mechanize
import json
import urllib
import urllib2
import sys
import os
import redis

import logging
logger = logging.getLogger(__name__)
logging.basicConfig()
logger.setLevel(logging.DEBUG)


# Bottle
bottle = Bottle()
debug(True)

# Global vars
br = None # mechanize browser
errores = None
CRONTIME = 120
config = Config()

# Endpoints
BASE_ENDPOINT      = 'https://ing.ingdirect.es/'
LOGIN_ENDPOINT     = BASE_ENDPOINT + 'genoma_login/rest/session'
POST_AUTH_ENDPOINT = BASE_ENDPOINT + 'genoma_api/login/auth/response'
CLIENT_ENDPOINT    = BASE_ENDPOINT + 'genoma_api/rest/client'
PRODUCTS_ENDPOINT  = BASE_ENDPOINT + 'genoma_api/rest/products'

ING_NOTIFICADOR = "https://ing-notificator.appspot.com/auth_complete?app="

PUSHBULLET_ENDPOINT = "https://api.pushbullet.com/oauth2/token"
PUSHBULLET_OAUTH = "https://www.pushbullet.com/authorize?client_id={client_id}&redirect_uri={notificator_uri}{app_uri}&response_type=token&scope=everything"


# Diccionario de relacion entre productNumber y alias
accounts_aliases = {}

def set_alias(account):
    global accounts_aliases

    if account.has_key("productNumber"):
        accounts_aliases[account["productNumber"]] = account.get("alias", account["name"])
    elif account.has_key("cardNumber"):
        accounts_aliases[account["cardNumber"]] = account.get("alias", account["name"])
    else:
        raise Exception("Cuenta sin productNumber o cardNumber")

def get_alias(transaction):
    if transaction.has_key("productNumber"):
        return accounts_aliases.get(transaction["productNumber"])
    elif transaction.has_key("cardNumber"):
        return accounts_aliases.get(transaction["cardNumber"])
    else:
        raise Exception("Transaction sin productNumber o cardNumber")

def init_browser():
    global br

    WEB_USER_AGENT = 'Mozilla/5.0 (Linux; Android 4.2.1; en-us; Nexus 4 Build/JOP40D) AppleWebKit/535.19 (KHTML, ' \
                             'like Gecko) Chrome/18.0.1025.166 Mobile Safari/535.19'

    br = mechanize.Browser()
    br.set_handle_robots(False)
    br.addheaders = [('User-agent', WEB_USER_AGENT)]
    #br.set_proxies({"http": "tcp://0.tcp.ngrok.io:13183", "https": "tcp://0.tcp.ngrok.io:13183"})

def add_headers(header):
    br.addheaders = header + br.addheaders

def convert_headers():
    heads = {}
    for h in br.addheaders:
        heads[h[0]] = h[1]

    return heads

def fetch_accounts():
    logger.info(sys._getframe().f_code.co_name)
    add_headers([("Accept", '*/*')])
    add_headers([('Content-Type', 'application/json; charset=utf-8')])
    req = br.request_class(PRODUCTS_ENDPOINT)
    try:
        res = br.open(req)
    except Exception as e:
        logger.error("Error obteniendo cuentas: %s", e)
        raise e
    res_json = json.loads(res.read())

    for account in res_json:
        set_alias(account)

    return res_json

def fetch_last_transactions(account):
    logger.info(sys._getframe().f_code.co_name)

    end_date = date.today()
    start_date = date.today() - timedelta(days = 30)
    params = {
      "fromDate": start_date.strftime('%d/%m/%Y'),
      "toDate": end_date.strftime('%d/%m/%Y'),
      "limit": 25,
      "offset": 0
    }
    logger.info("Params para coger transactions: %s", params)

    add_headers([("Accept", 'application/json, text/javascript, */*; q=0.01')])
    add_headers([('Content-Type', 'application/json; charset=utf-8')])
    req = br.request_class("%s/%s/movements?%s" % (
        PRODUCTS_ENDPOINT, account["uuid"], urllib.urlencode(params)))
    logger.info("Query a %s", req.get_full_url())
    try:
        start_time = time.time()
        res = br.open(req)
        req_time = time.time() - start_time
    except Exception as e:
        logger.error("Error solicitando movimientos: %s", e)
        raise e

    logger.info("Tiempo de la request: %s", req_time)
    transactions = json.loads(res.read())

    for t in transactions.get("elements", []):
        notify_and_save_transaction(t)

def notify_and_save_transaction(transaction):
    logger.info(sys._getframe().f_code.co_name)
    uuid = transaction["uuid"]

    if not config.existe_movimiento(uuid):
        config.add_movimiento(uuid)
        pushbullet_notification(transaction)

def pushbullet_notification(transaction):
    logger.info(sys._getframe().f_code.co_name)

    body = "%s: %s (%s)" % (transaction.get("description"),transaction.get("amount"),transaction.get("balance"))
    try:
        pushbullet.send(config.get_pushbullet(), get_alias(transaction), body=body)
        logger.info("ING - Movimiento: %s", body)
    except KeyError as e:
        logger.error("No hay alias para la transation: %s", transaction)
    except Exception as e:
        logger.error("Error enviando pushbullet: %s", e)
        raise e

def get_uri():
    logger.info(sys._getframe().f_code.co_name)
    if isDev():
        return "http://localhost:%s" % os.environ.get("PORT", 5000)
    else:
        return "https://%s" % request.environ.get("HTTP_HOST")

def login():
    logger.info(sys._getframe().f_code.co_name)

    logger.info("dni: %s, fecha: %s, pass: %s" % (config.get_dni(), config.get_fecha(), config.get_pass()))
    if not config.get_dni() or not config.get_fecha() or not config.get_pass():
        raise Exception("Falta cargar los datos: <a href='%s/config'>Load</a>" % get_uri())

    params = {
      "loginDocument": {
        "documentType": 0,
        "document": config.get_dni()
      },
      "birthday": config.get_fecha(),
      "companyDocument": None,
      "device": 'desktop'
    }
    data = json.dumps(params)

    add_headers([("Accept", 'application/json, text/javascript, */*; q=0.01')])
    add_headers([('Content-Type', 'application/json; charset=utf-8')])
    req = br.request_class(LOGIN_ENDPOINT, headers=convert_headers())
    logger.info("Login headers: %s", br.addheaders)
    try:
        res = br.open(req, data=data)
    except Exception as e:
        logger.error("Error enviando login. URL: %s. Data: %s", req.get_full_url(), data)
        raise e

    pinData = json.loads(res.read())
    logger.info("pinPositions: %s", pinData["pinPositions"])

    try:
        pinpad = process_pin_images(pinData["pinpad"])
    except Exception as e:
        logger.error("Exception en process_pin_images: %s", e)
        raise e
    logger.info("Pinpad: %s", pinpad)

    password = config.get_pass()
    digits = []
    for i in range(0,3):
        digits.append(int(password[pinData["pinPositions"][i] - 1]))

    logger.info("Digits: %s", digits)

    codecDigits = []
    for i in digits:
        codecDigits.append(pinpad.index(i))

    logger.info("codecDigits: %s", codecDigits)

    try:
        ticket = send_pinpad(codecDigits)
    except Exception as e:
        logger.error("Exception en send_pinpad: %s", e)
        raise e
    logger.info("ticket: %s", ticket)

    post_auth(ticket)

    return "Ok"

def send_pinpad(digits):
    logger.info(sys._getframe().f_code.co_name)
    fields = {"pinPositions": digits}
    add_headers([('Content-Type', 'application/json; charset=utf-8')])
    req = br.request_class(LOGIN_ENDPOINT, headers=convert_headers())
    req.get_method = lambda: "PUT"
    res = br.open(req, data=json.dumps(fields))
    res_json = json.loads(res.read())
    return res_json["ticket"]

def post_auth(ticket):
    logger.info(sys._getframe().f_code.co_name)
    headers = {'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'}
    data = "ticket=%s&device=desktop" % ticket
    req = br.request_class(POST_AUTH_ENDPOINT, headers=headers)

    try:
        res = br.open(req, data=data)
    except mechanize.HTTPError as e:
        msg = "Error en post_auth"
        logger.error("%s\nURL: %s\nData: %s\nHeaders: %s\nResp: %s\nException: %s",
                msg, req.get_full_url(), data, req.headers, e.read(), e)
        raise e

def process_pin_images(images_array):
    logger.info(sys._getframe().f_code.co_name)
    pinpad = []

    for n,bimg in enumerate(images_array):
        fichero = StringIO(b64decode(bimg))
        img = Image.open(fichero)
        pix = img.load()
        pinpad.append(parse_pin(pix))

    return pinpad

def isDev():
    logger.info(sys._getframe().f_code.co_name)
    logger.info("Env %s", os.environ.get('DYNO'))
    return os.environ.get('DYNO') == None

def isPro():
    logger.info(sys._getframe().f_code.co_name)
    logger.info("Env %s", os.environ.get('DYNO'))
    return os.environ.get('DYNO') != None

def render_template(template_name, **context):
    logger.info(sys._getframe().f_code.co_name)

    extensions = context.pop('extensions', [])
    globals = context.pop('globals', {})

    jinja_env = Environment(
            loader=FileSystemLoader(os.path.join(os.path.dirname(__file__), 'templates')),
            extensions=extensions,
            )
    jinja_env.globals.update(globals)

    #jinja_env.update_template_context(context)
    return jinja_env.get_template(template_name).render(context)

@bottle.get('/cron')
def run_cron():
    Timer(0, cron, []).start()
    return "Proceso arrancado"

def cron():
    """
    Proceso principal que gestiona el login, obtener cuentas y parsearlas
    en busca de nuevos movimientos
    """
    logger.info(sys._getframe().f_code.co_name)

    config.set_last(datetime.now())

    global errores
    errores = None

    init_browser()
    logger.info("br object: %s", br)

    try:
        login_output = login()
    except Exception as e:
        errores = "Error con el login"
        logger.error(e)
        logger.info("Cron temporizado dentro de %s seg", CRONTIME)
        Timer(CRONTIME, cron, []).start()
        return

    try:
        accounts = fetch_accounts()
    except Exception as e:
        errores = "Error cogiendo las cuentas"
        logger.error(e)
        accounts = []

    for account in accounts:
        try:
            logger.info("Obteniendo movimientos de %s", account["name"])
            # Tras varias peticiones de movimientos consecutivas, el servidor
            # empieza a meter delays de 30" en las respuestas
            fetch_last_transactions(account)
        except Exception as e:
            errores = "Error analizando movimientos"
            logger.error(e)

    logger.info("Cron temporizado dentro de %s seg", CRONTIME)
    Timer(CRONTIME, cron, []).start()

@bottle.get('/config')
def config_get():
    """
    Nos muestra un formulario para meter los datos
    """
    logger.info(sys._getframe().f_code.co_name)

    body = render_template('config.html', **locals())
    return body

@bottle.post('/config')
def config_post():
    """
    Recibe el formulario rellenado por el usuario
    Tras almacenar los datos, comienza el analisis de movimientos
    """
    logger.info(sys._getframe().f_code.co_name)

    config.set_dni(request.forms.get("dni"))
    config.set_pass(request.forms.get("password"))
    config.set_fecha(request.forms.get("fecha"))

    logger.info("Actualizada config sin token pushbullet")

    logger.info("Arrancado el cron que analiza los movimientos")
    Timer(0, cron, []).start()

    body = render_template('config_complete.html', **locals())
    return body


@bottle.route('/kaffeine')
def kaffeine():
    """
    Registra app en kaffeine sin bedtime
    """
    logger.info(sys._getframe().f_code.co_name)

    app_name = request.environ.get("HTTP_HOST").split(".")[0]
    hora_dormir_utc = "00:00"

    br = mechanize.Browser()
    br.set_handle_robots(False)

    try:
        soup = BeautifulSoup(br.open("http://kaffeine.herokuapp.com/"), "html.parser")
    except Exception as e:
        return "Error conectando con kaffeine.herokuapp.com: %s" % e

    csrf_token = soup.find(name="meta",attrs={"name": "csrf-token"}).get("content")
    req = br.request_class("http://kaffeine.herokuapp.com/register", headers={"X-CSRF-Token": csrf_token})
    try:
        data = "name=%s&nap=true&bedtime=%s" % (app_name, urllib2.quote(hora_dormir_utc)
        logger.info("Data: %s" % data)
        res = br.open(req, data=data)
    except Exception as e:
        return "Error registrando la app en kaffeine.herokuapp.com: %s" % e

    if res.code == 200:
        return "App registrada correctamente en kaffeine.herokuapp.com"
    elif res.code == 201:
        return "La app ya estaba registrada"
    else:
        return "Codigo desconocido: %s" % res.code


@bottle.route('/auth_complete')
def auth_complete():
    """
    Pagina donde cargaremos un javascript que leera el token y lo registrara
    """
    logger.info(sys._getframe().f_code.co_name)

    try:
        body = render_template('auth.html', **locals())
    except Exception as e:
        logger.error("Excepcion renderizando auth.html: %s", e)
        return "Error rendering auth.html"

    return body

@bottle.route('/save_token')
def save_token():
    """
    El javascript de auth_complete enviara aqui el token de la url
    """
    logger.info(sys._getframe().f_code.co_name)
    token = request.params.get("token")
    config.set_pushbullet(token)
    logger.info("Actualizando token: %s", token)

    try:
        logger.info("Probando envio de pushbullet")
        pushbullet.send(config.get_pushbullet(), "Registro correcto", body="Prueba de envio")
    except Exception as e:
        logger.error("Error enviando pushbullet: %s", e)
        raise e

    return 'Token registrando correctamente. Ahora deberias recibir un pushbullet de prueba'

@bottle.route('/')
def index():
    logger.info(sys._getframe().f_code.co_name)
    try:
        cfg = config.get_dni() != None
        cfg_pushbullet = config.get_pushbullet() != None

        # Si hace mucho tiempo que no se ejecuta, vuelve a programar el cron
        last_update = config.get_last()
        if last_update:
            diff = datetime.now() - last_update
            if diff > timedelta(minutes=10):
                logger.info("Reactivando cron, hace mucho que no se ejecuta: %s", diff)
                Timer(0, cron, []).start()

        is_dev = isDev()
        transaction_num = config.num_movimientos()
        auth_pushbullet_url = PUSHBULLET_OAUTH.format(
                client_id=config.get_pushbullet_client_id(),
                notificator_uri=urllib2.quote(ING_NOTIFICADOR, safe=""),
                app_uri=urllib2.quote(get_uri(), safe=""))
    except redis.ConnectionError as e:
        logger.error("Error conectando con el servidor redis: %s", e)
        body = render_template('redis.html', **locals())
        return body
    except Exception as e:
        logger.error("Error generando variables para el template index.html: %s", e)
        return "Error templating index.html vars"

    try:
        errores_local = errores
        app_name = request.environ.get("HTTP_HOST").split(".")[0]
        body = render_template('index.html', **locals())
    except Exception as e:
        logger.error("Excepcion renderizando index.html: %s", e)
        return "Error rendering index.html"

    return body

bottle.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
