from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class ShopProfile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), default="FAKKAD JEWELLERS")
    gst = db.Column(db.String(50), default="09BMRPS8447R1Z1")
    address = db.Column(db.String(200), default="Madhogarh, Jalaun")
    mobile = db.Column(db.String(20), default="9451508591")

class Inventory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    metal = db.Column(db.String(10)) # Gold or Silver
    item_name = db.Column(db.String(50))
    weight = db.Column(db.Float, default=0.0)

class BillRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(20))
    customer = db.Column(db.String(100))
    mobile = db.Column(db.String(15))
    total = db.Column(db.Float)
    paid = db.Column(db.Float)
    balance = db.Column(db.Float)