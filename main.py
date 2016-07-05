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
from models import Transaction, Config, Base
from jinja2 import Template,Environment,FileSystemLoader
from sqlalchemy import create_engine
from bottle.ext import sqlalchemy

from chequea_imagenes import parse_pin
import pushbullet
import config

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

import logging
logger = logging.getLogger(__name__)
logging.basicConfig()
logger.setLevel(logging.DEBUG)


bottle = Bottle()
engine = create_engine(os.environ["DATABASE_URL"], echo=False)
plugin = sqlalchemy.Plugin(
    engine, # SQLAlchemy engine created with create_engine function.
    Base.metadata, # SQLAlchemy metadata, required only if create=True.
    keyword='db', # Keyword used to inject session database in a route (default 'db').
    create=True, # If it is true, execute `metadata.create_all(engine)` when plugin is applied (default False).
    commit=True, # If it is true, plugin commit changes after route is executed (default True).
    use_kwargs=False # If it is true and keyword is not defined, plugin uses **kwargs argument to inject session database (default False).
)
bottle.install(plugin)

# Bottle debug
debug(False)

# Global vars
br = None # mechanize browser
errores = None
CRONTIME = 120

# Endpoints
BASE_ENDPOINT      = 'https://ing.ingdirect.es/'
LOGIN_ENDPOINT     = BASE_ENDPOINT + 'genoma_login/rest/session'
POST_AUTH_ENDPOINT = BASE_ENDPOINT + 'genoma_api/login/auth/response'
CLIENT_ENDPOINT    = BASE_ENDPOINT + 'genoma_api/rest/client'
PRODUCTS_ENDPOINT  = BASE_ENDPOINT + 'genoma_api/rest/products'

PUSHBULLET_ENDPOINT = "https://api.pushbullet.com/oauth2/token"
PUSHBULLET_OAUTH = "https://www.pushbullet.com/authorize?client_id={client_id}&redirect_uri={server_uri}%2Fauth_complete&response_type=token&scope=everything"

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
    # proxy no soportado por GAE

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

def fetch_last_transactions(account, db):
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
        notify_and_save_transaction(t, db)

def notify_and_save_transaction(transaction, db):
    logger.info(sys._getframe().f_code.co_name)
    uuid = transaction["uuid"]

    if not db.query(Transaction).filter_by(uuid=uuid).first():
        pushbullet_notification(transaction, db)
        t = Transaction(
                uuid = uuid,
                alias = get_alias(transaction),
                descr = transaction.get("description"),
                balance = transaction.get("balance"),
                amount = transaction.get("amount"),
                date = datetime.strptime(transaction.get("effectiveDate"),"%d/%m/%Y")
                )
        db.add(t)

def pushbullet_notification(transaction, db):
    logger.info(sys._getframe().f_code.co_name)

    body = "%s: %s (%s)" % (transaction.get("description"),transaction.get("amount"),transaction.get("balance"))
    try:
        pushbullet.send(db, get_alias(transaction), body=body)
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

def login(db):
    logger.info(sys._getframe().f_code.co_name)

    if not config.get(db, "dni") or not config.get(db, "fecha_nacimiento") or not config.get(db, "password"):
        raise Exception("Falta cargar los datos en NDB: <a href='%s/config'>Load</a>" % get_uri())

    params = {
      "loginDocument": {
        "documentType": 0,
        "document": config.get(db, "dni")
      },
      "birthday": config.get(db, "fecha_nacimiento"),
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

    password = config.get(db, "password")
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
def run_cron(db):
    Timer(0, cron, [db]).start()
    return "Proceso arrancado"

def cron(db):
    """
    Proceso principal que gestiona el login, obtener cuentas y parsearlas
    en busca de nuevos movimientos
    """
    logger.info(sys._getframe().f_code.co_name)

    # Cambiar por last_update
    try:
        c = db.query(Config).first()
        c.last_update = datetime.now()
        db.commit()
    except Exception as e:
        msg = "Error actualizando last_update"
        logger.error("%s: %s", msg, e)
        return msg

    global errores
    errores = None

    init_browser()
    logger.info("br object: %s", br)

    try:
        login_output = login(db)
    except Exception as e:
        errores = "Error con el login"
        logger.error(e)

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
            fetch_last_transactions(account, db)
        except Exception as e:
            errores = "Error analizando movimientos"
            logger.error(e)

    logger.info("Cron temporizado dentro de %s seg", CRONTIME)
    Timer(CRONTIME, cron, [db]).start()

@bottle.get('/config')
def config_get(db):
    """
    Nos muestra un formulario para meter los datos
    """
    logger.info(sys._getframe().f_code.co_name)

    body = render_template('config.html', **locals())
    return body

@bottle.post('/config')
def config_post(db):
    """
    Recibe el formulario rellenado por el usuario
    Tras almacenar los datos, comienza el analisis de movimientos
    """
    logger.info(sys._getframe().f_code.co_name)

    dni = request.forms.get("dni")
    password = request.forms.get("password")
    fecha = request.forms.get("fecha")

    if config.get(db):
        logger.info("Actualizada config sin token pushbullet")
        try:
            c = db.query(Config).first()
        except Exception as e:
            msg = "Error obteniendo config de la bbdd"
            logger.error("%s: %s", msg, e)
            return msg

        c.dni = dni
        c.password = password
        c.fecha_nacimiento = fecha
        try:
            db.commit()
        except Exception as e:
            msg = "Error actualizando config en la bbdd"
            logger.error("%s: %s", msg, e)
            return msg
    else:
        logger.info("Creada config sin token pushbullet")

        c = Config(dni=dni, password=password, fecha=fecha)

        try:
            db.add(c)
        except Exception as e:
            msg = "Error creando config en la bbdd"
            logger.error("%s: %s", msg, e)
            return msg

    logger.info("Arrancado el cron que analiza los movimientos")
    Timer(0, cron, [db]).start()

    return "Configuracion definida correctamente"


@bottle.route('/kaffeine')
def kaffeine(db):
    """
    Registra app en kaffeine
    """
    logger.info(sys._getframe().f_code.co_name)

    app_name = request.environ.get("HTTP_HOST").split(".")[0]
    hora_dormir_utc = "23:00"

    br = mechanize.Browser()
    br.set_handle_robots(False)

    try:
        soup = BeautifulSoup(br.open("http://kaffeine.herokuapp.com/"), "html.parser")
    except Exception as e:
        return "Error conectando con kaffeine.herokuapp.com: %s" % e

    csrf_token = soup.find(name="meta",attrs={"name": "csrf-token"}).get("content")
    req = br.request_class("http://kaffeine.herokuapp.com/register", headers={"X-CSRF-Token": csrf_token})
    try:
        logger.info("Data: name=%s&nap=true&bedtime=%s" % (app_name, urllib2.quote(hora_dormir_utc)))
        res = br.open(req, data="name=%s&nap=true&bedtime=%s" % ("appname", urllib2.quote(hora_dormir_utc)))
    except Exception as e:
        return "Error registrando la app en kaffeine.herokuapp.com: %s" % e

    if res.code == 200:
        return "App registrada correctamente en kaffeine.herokuapp.com"
    elif res.code == 201:
        return "La app ya estaba registrada"
    else:
        return "Codigo desconocido: %s" % res.code


@bottle.route('/auth_complete')
def auth_complete(db):
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
def save_token(db):
    """
    El javascript de auth_complete enviara aqui el token de la url
    """
    logger.info(sys._getframe().f_code.co_name)
    token = request.params.get("token")
    logger.info("Actualizando token: %s", token)
    try:
        c = db.query(Config).first()
        c.pushbullet_token = token
        db.commit()
    except Exception as e:
        msg = "Error actualizando token"
        logger.error("%s: %s", msg, e)
        return msg

    try:
        logger.info("Probando envio de pushbullet")
        pushbullet.send(db, "Registro correcto", body="Prueba de envio")
    except Exception as e:
        logger.error("Error enviando pushbullet: %s", e)
        raise e

    return 'Token registrando correctamente. Ahora deberias recibir un pushbullet de prueba'

@bottle.route('/')
def index(db):
    logger.info(sys._getframe().f_code.co_name)
    try:
        cfg = config.get(db) != None
        cfg_pushbullet = config.get(db, "pushbullet_token") != None

        # kaffeine.herokuapp.com hace get a / cada 30', pero para entre la 1:00 y las 7:00
        # Cuando nos vuelva a hacer get por la mañana, despertamos a cron
        # Tambien despierta a cron si pedimos / y hace mucho que no se ejecuta
        last_update = config.get(db, "last_update")
        if last_update:
            diff = datetime.now() - last_update
            if diff > timedelta(minutes=30):
                logger.info("Reactivando cron, hace mucho que no se ejecuta: %s", diff)
                Timer(0, cron, [db]).start()

        is_dev = isDev()
        transaction_num = db.query(Transaction).count()
        redirect_url = urllib2.quote(get_uri(), safe="")
        logger.info("redirect_url: %s", redirect_url)
        auth_pushbullet_url = PUSHBULLET_OAUTH.format(client_id=config.PUSHBULLET_CLIENT_ID, server_uri=redirect_url)
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
