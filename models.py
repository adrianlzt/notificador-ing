from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, String, Float, DateTime, Integer, Sequence

Base = declarative_base()

class Transaction(Base):
    __tablename__ = 'transaction'

    uuid = Column(String(400), primary_key=True)
    account_alias = Column(String(70))
    description = Column(String(200))
    balance = Column(Float())
    amount = Column(Float())
    effectiveDate = Column(DateTime())

    def __init__(self, uuid=None, alias=None, descr=None, balance=None, amount=None, date=None):
        self.uuid = uuid
        self.account_alias = alias
        self.description = descr
        self.balance = balance
        self.amount = amount
        self.effectiveDate = date

# TODO: que solo pueda existir una config
class Config(Base):
    instance = None

    __tablename__ = 'config'

    id = Column(Integer, Sequence('id_seq'), primary_key=True)
    dni = Column(String(11))
    password = Column(String(10))
    fecha_nacimiento = Column(String(15))
    pushbullet_token = Column(String(50))
    last_update = Column(DateTime())

    def __init__(self, dni=None, password=None, fecha=None, token=None):
        self.dni = dni
        self.password = password
        self.fecha_nacimiento = fecha
        self.pushbullet_token = token
        self.last_update = None

    def to_dict():
        return {"dni": self.dni, "password": self.password,
                "fecha_nacimiento": self.fecha_nacimiento,
                "pushbullet_token": self.pushbullet_token,
                "last_update": self.last_update}
