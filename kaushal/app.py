from flask import Flask, render_template, request, send_file, redirect, url_for, send_from_directory, jsonify
from flask_sqlalchemy import SQLAlchemy
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from datetime import datetime
import os
import pandas as pd

app = Flask(__name__)

# --- DATABASE CONFIGURATION ---
# This looks for Render's Database URL, otherwise uses a local file for testing
uri = os.getenv("DATABASE_URL", "sqlite:///jewellery_pro.db")
if uri and uri.startswith("postgres://"):
    uri = uri.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- MODELS ---
class ShopProfile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    address = db.Column(db.String(200))
    gst = db.Column(db.String(50))
    mobile = db.Column(db.String(20))

class Inventory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    metal = db.Column(db.String(20))
    item_name = db.Column(db.String(100))
    weight = db.Column(db.Float)

# New Model to keep transactions forever
class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(20))
    customer = db.Column(db.String(100))
    mobile = db.Column(db.String(20))
    metal = db.Column(db.String(20))
    items = db.Column(db.Text)
    net_weight = db.Column(db.Float)
    old_weight = db.Column(db.Float)
    total_amount = db.Column(db.Float)
    paid_amount = db.Column(db.Float)
    balance_due = db.Column(db.Float)

BILL_FOLDER = "generated_bills"
os.makedirs(BILL_FOLDER, exist_ok=True)

with app.app_context():
    db.create_all()
    shop = ShopProfile.query.first()
    if not shop:
        shop = ShopProfile(
            name="Fakkad Jewellers", 
            gst="09BMRPS8447R1Z1",
            address="KHUNNI GHEE WALE KE BAGAL ME,MADHOGARH,JALAUN(UP)",
            mobile="9451508591"
        )
        db.session.add(shop)
        db.session.commit()

@app.route("/", methods=["GET", "POST"])
def bill():
    shop = ShopProfile.query.first()
    bill_data = None
    gold_items = [i.item_name for i in Inventory.query.filter_by(metal="Gold").all()]
    silver_items = [i.item_name for i in Inventory.query.filter_by(metal="Silver").all()]

    if request.method == "POST":
        customer = request.form["customer"]
        mobile = request.form["mobile"]
        metal = request.form["metal"]
        net_w = float(request.form.get("net_weight") or 0)
        old_w = float(request.form.get("old_weight") or 0)
        math_r = float(request.form.get("math_rate") or 0)
        making = float(request.form.get("making") or 0)
        extra_adj = float(request.form.get("extra_adj") or 0)
        gst_p = float(request.form.get("gst_per") or 0)
        disc = float(request.form.get("discount") or 0)
        paid = float(request.form.get("paid_amount") or 0)
        display_rate = float(request.form.get("display_rate") or 0)

        item_names = request.form.getlist("item_name[]")
        item_weights = request.form.getlist("item_weight[]")
        purchased_items = []
        for n, w in zip(item_names, item_weights):
            if n and w:
                purchased_items.append((n, float(w)))
                stock = Inventory.query.filter_by(metal=metal, item_name=n).first()
                if stock: stock.weight = round(max(0, stock.weight - float(w)), 3)

        billing_w = net_w - old_w
        if metal == "Gold":
            purity = float(request.form.get("purity", 75))
            base = (math_r / 10) * billing_w
            m_amt = base * (purity / 100)
            mk_amt = base * ((making + extra_adj) / 100)
            sub_total = m_amt + mk_amt
            total_with_gst = sub_total + (sub_total * (gst_p / 100))
            total = total_with_gst * 1.002911 
            p_label = f"Gold {purity}%"
        else:
            m_amt = (math_r / 1000) * billing_w
            mk_amt = making + (m_amt * (extra_adj / 100))
            sub_total = m_amt + mk_amt
            total = sub_total + (sub_total * (gst_p / 100))
            p_label = "Silver"

        final_total = round(max(0, total - disc), 2)
        gst_final = round((sub_total * (gst_p / 100)), 2)
        balance = round(final_total - paid, 2)
        item_str = "|".join([f"{n}:{w}" for n, w in purchased_items])

        # SAVE TO PERMANENT DATABASE
        new_row = Transaction(
            date=datetime.now().strftime("%d-%m-%Y"),
            customer=customer, mobile=mobile, metal=metal,
            items=item_str, net_weight=net_w, old_weight=old_w,
            total_amount=final_total, paid_amount=paid, balance_due=balance
        )
        db.session.add(new_row)
        db.session.commit()

        bill_data = {
            "Date": new_row.date, "Customer": customer, "Mobile": mobile, 
            "Metal": metal, "NetW": net_w, "OldW": old_w, "Purity": p_label,
            "Rate": display_rate, "Gst": gst_final, "Making_Input": making,
            "Total": final_total, "Paid": paid, "Balance": balance, "Discount": disc,
            "Items": item_str
        }

    return render_template("bill.html", bill=bill_data, shop=shop, gold_list=gold_items, silver_list=silver_items)

@app.route("/records")
def view_records():
    # Load all records from the database
    transactions = Transaction.query.order_by(Transaction.id.desc()).all()
    return render_template("records.html", transactions=transactions)

@app.route("/delete_record/<int:record_id>", methods=["POST"])
def delete_record(record_id):
    record = Transaction.query.get(record_id)
    if record:
        db.session.delete(record)
        db.session.commit()
        return jsonify({"success": True}), 200
    return jsonify({"success": False}), 404

@app.route("/download_excel")
def download_excel():
    trans = Transaction.query.all()
    data = [{
        "Date": t.date, "Customer": t.customer, "Mobile": t.mobile,
        "Metal": t.metal, "Items": t.items, "Net Weight": t.net_weight,
        "Total": t.total_amount, "Paid": t.paid_amount, "Balance": t.balance_due
    } for t in trans]
    df = pd.DataFrame(data)
    temp_path = "/tmp/transactions.xlsx"
    df.to_excel(temp_path, index=False)
    return send_file(temp_path, as_attachment=True)

# Keep other routes (admin, pdf, bill_gallery) same as before...
# (Omitted here for brevity, but they will work with 'db')

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)