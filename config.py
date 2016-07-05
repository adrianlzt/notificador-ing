from models import Config

import logging
logger = logging.getLogger(__name__)

PUSHBULLET_CLIENT_ID = "QQzdERheIQm7VXgnbT6HbyvC6ECQexrw"

def get(db,key=None):
    """
    Devuelve el elemento que pidamos por parametro, o None si no existe
    Si no pasamos parametro devuelve el objeto entero de conf o None si no existe
    """
    #if not db.get_bind().has_table("config"):
    #    return None
    if key:
        if hasattr(db.query(Config).first(), key):
            return getattr(db.query(Config).first(), key)
        else:
            return None
    else:
        return db.query(Config).first()
