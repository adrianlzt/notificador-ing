import redis
import os
from datetime import datetime

import logging
logger = logging.getLogger(__name__)

PREFIX = "ing-notificador:"
DNI = PREFIX + "dni"
PASS = PREFIX + "pass"
FECHA = PREFIX + "fecha_nacimiento"
PUSHBULLET = PREFIX + "pushbullet"
LAST = PREFIX + "last"

class Config(object):
    def __init__(self):
        self.r = redis.from_url(os.environ.get("REDIS_URL"))
        self.key_movimientos = PREFIX+"movimientos"

    def get_pushbullet_client_id(self):
        return "QQzdERheIQm7VXgnbT6HbyvC6ECQexrw"

    def get_dni(self):
        return self.r.get(DNI)

    def set_dni(self,dni):
        return self.r.set(DNI,dni)

    def get_pass(self):
        return self.r.get(PASS)

    def set_pass(self,password):
        return self.r.set(PASS,password)

    def get_fecha(self):
        return self.r.get(FECHA)

    def set_fecha(self,fecha_nacimeinto):
        return self.r.set(FECHA,fecha_nacimeinto)

    def get_pushbullet(self):
        return self.r.get(PUSHBULLET)

    def set_pushbullet(self,token):
        return self.r.set(PUSHBULLET,token)

    def get_last(self):
        last = self.r.get(LAST)
        if last:
            return datetime.strptime(last, "%Y-%m-%d %H:%M:%S.%f")
        return None

    def set_last(self,last):
        return self.r.set(LAST,last)

    def existe_movimiento(self,movimiento):
        return self.r.sismember(self.key_movimientos,movimiento)

    def add_movimiento(self,movimiento):
        return self.r.sadd(self.key_movimientos,movimiento)

    def num_movimientos(self):
        return self.r.scard(self.key_movimientos)
