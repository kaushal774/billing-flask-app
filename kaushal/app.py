import os
from datetime import datetime
from flask import Flask, render_template, request, send_file, redirect, url_for, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
import pandas as pd
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

app = Flask(__name__)

# --- DATABASE CONFIGURATION ---
# Works locally (SQLite) and on servers like Render/Heroku (PostgreSQL)
database_url = os.getenv("DATABASE_URL", "sqlite:///fakkad_jewellers.db")
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Folder for PDF storage
PDF_STORE = "generated_bills"
if not os.path.exists(PDF_STORE):
    os.makedirs(PDF_STORE)

# --- MODELS ---
class ShopProfile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), default="FAKKAD JEWELLERS")
    gst = db.Column(db.String(50), default="09BMRPS8447R1Z1")
    address = db.Column(db.String(200), default="Madhogarh, Jalaun")
    mobile = db.Column(db.String(20), default="9451508591")

class Inventory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    metal = db.Column(db.String(10)) 
    item_name = db.Column(db.String(100))
    weight = db.Column(db.Float, default=0.0)

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(20))
    customer = db.Column(db.String(100))
    mobile = db.Column(db.String(15))
    metal = db.Column(db.String(10))
    total = db.Column(db.Float)
    paid = db.Column(db.Float)
    balance = db.Column(db.Float)

# Initialize Database tables
with app.app_context():
    db.create_all()
    if not ShopProfile.query.first():
        db.session.add(ShopProfile())
        db.session.commit()

# --- ROUTES ---

@app.route("/", methods=["GET", "POST"])
def index():
    shop = ShopProfile.query.first()
    bill_data = None
    
    # Get stock lists for the dropdowns in bill.html
    gold_items = [i.item_name for i in Inventory.query.filter_by(metal="Gold").all()]
    silver_items = [i.item_name for i in Inventory.query.filter_by(metal="Silver").all()]

    if request.method == "POST":
        # Capture Form Data
        cust_name = request.form.get('customer')
        cust_mobile = request.form.get('mobile')
        metal_type = request.form.get('metal')
        net_w = float(request.form.get('net_weight', 0))
        old_w = float(request.form.get('old_weight', 0))
        paid = float(request.form.get('paid_amount', 0))
        disc = float(request.form.get('discount', 0))
        
        # Calculation Logic (Matches your JavaScript)
        math_rate = float(request.form.get('math_rate', 0))
        making = float(request.form.get('making', 0))
        extra_adj = float(request.form.get('extra_adj', 0))
        gst_per = float(request.form.get('gst_per', 3))
        billing_w = net_w - old_w
        
        total = 0
        if math_rate > 0 and billing_w > 0:
            if metal_type == "Gold":
                purity = float(request.form.get('purity', 75))
                base_val = (math_rate / 10) * billing_w
                subtotal = (base_val * (purity/100)) + (base_val * ((making + extra_adj)/100))
                total = (subtotal + (subtotal * (gst_per/100))) * 1.002911
            else:
                metal_amt = (math_rate / 1000) * billing_w
                subtotal = metal_amt + making + (metal_amt * (extra_adj/100))
                total = subtotal + (subtotal * (gst_per/100))

        final_total = round(max(0, total - disc))
        balance = final_total - paid

        # Update Inventory (Deduct Sold Weight)
        sold_items = request.form.getlist('item_name[]')
        sold_weights = request.form.getlist('item_weight[]')
        for name, weight in zip(sold_items, sold_weights):
            item = Inventory.query.filter_by(metal=metal_type, item_name=name).first()
            if item and weight:
                item.weight = round(max(0, item.weight - float(weight)), 3)

        # Save Transaction to Database
        new_trans = Transaction(
            date=datetime.now().strftime("%d-%m-%Y"),
            customer=cust_name, mobile=cust_mobile, metal=metal_type,
            total=final_total, paid=paid, balance=balance
        )
        db.session.add(new_trans)
        db.session.commit()

        # Preparing bill object for the frontend success message
        bill_data = {
            "Customer": cust_name, "Mobile": cust_mobile, "Metal": metal_type,
            "Total": final_total, "Paid": paid, "Balance": balance, 
            "NetW": net_w, "Rate": request.form.get('display_rate')
        }

    return render_template("bill.html", shop=shop, bill=bill_data, gold_list=gold_items, silver_list=silver_items)

@app.route("/admin", methods=["GET", "POST"])
def admin():
    shop = ShopProfile.query.first()
    if request.method == "POST" and 'add_stock' in request.form:
        metal = request.form.get('metal')
        name = request.form.get('item_name').upper()
        weight = float(request.form.get('weight', 0))
        
        existing = Inventory.query.filter_by(metal=metal, item_name=name).first()
        if existing:
            existing.weight += weight
        else:
            db.session.add(Inventory(metal=metal, item_name=name, weight=weight))
        db.session.commit()
        return redirect(url_for('admin'))

    inventory = Inventory.query.all()
    return render_template("admin.html", shop=shop, inventory=inventory)

@app.route("/delete_inventory/<int:item_id>", methods=["POST"])
def delete_inventory(item_id):
    item = Inventory.query.get(item_id)
    if item:
        db.session.delete(item)
        db.session.commit()
        return '', 204
    return 'Not Found', 404

@app.route("/records")
def records():
    trans = Transaction.query.order_by(Transaction.id.desc()).all()
    if not trans:
        return render_template("records.html", table=None)
    
    # Generate HTML Table for records.html using Pandas
    df = pd.DataFrame([{
        "ID": t.id, "Date": t.date, "Customer": t.customer, "Mobile": t.mobile,
        "Metal": t.metal, "Total": t.total, "Paid": t.paid, "Balance": t.balance
    } for t in trans])
    
    table_html = df.to_html(classes="table table-hover", index=False)
    return render_template("records.html", table=table_html)

@app.route("/delete_record/<int:index>", methods=["POST"])
def delete_record(index):
    all_records = Transaction.query.order_by(Transaction.id.desc()).all()
    if 0 <= index < len(all_records):
        db.session.delete(all_records[index])
        db.session.commit()
        return '', 204
    return 'Error', 400

@app.route("/pdf", methods=["POST"])
def generate_pdf():
    data = request.form
    shop = ShopProfile.query.first()
    filename = f"Invoice_{data.get('Customer')}_{datetime.now().strftime('%H%M%S')}.pdf"
    filepath = os.path.join(PDF_STORE, filename)

    doc = SimpleDocTemplate(filepath, pagesize=A4)
    styles = getSampleStyleSheet()
    content = []

    content.append(Paragraph(f"<b>{shop.name}</b>", styles['Title']))
    content.append(Paragraph(f"{shop.address} | GST: {shop.gst}", styles['Normal']))
    content.append(Spacer(1, 12))

    bill_info = [
        ["Customer:", data.get('Customer'), "Date:", datetime.now().strftime("%d-%m-%Y")],
        ["Mobile:", data.get('Mobile'), "Metal:", data.get('Metal')]
    ]
    t1 = Table(bill_info, colWidths=[80, 180, 80, 100])
    content.append(t1)
    content.append(Spacer(1, 20))

    summary = [
        ["Description", "Value"],
        ["Net Weight", f"{data.get('NetW')} gm"],
        ["Market Rate", f"Rs. {data.get('Rate')}"],
        ["Total Amount", f"Rs. {data.get('Total')}"],
        ["Paid Amount", f"Rs. {data.get('Paid')}"],
        ["Balance Due", f"Rs. {data.get('Balance')}"]
    ]
    t2 = Table(summary, colWidths=[200, 200])
    t2.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.grey),
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('GRID', (0,0), (-1,-1), 1, colors.black),
        ('PADDING', (0,0), (-1,-1), 8)
    ]))
    content.append(t2)
    
    doc.build(content)
    return send_file(filepath, as_attachment=True)

@app.route("/bill_gallery")
def bill_gallery():
    files = [f for f in os.listdir(PDF_STORE) if f.endswith('.pdf')]
    return render_template("gallery.html", files=files)

@app.route("/view_pdf/<filename>")
def view_pdf(filename):
    return send_from_directory(PDF_STORE, filename)

@app.route("/delete_pdf", methods=["POST"])
def delete_pdf():
    filename = request.json.get('filename')
    path = os.path.join(PDF_STORE, filename)
    if os.path.exists(path):
        os.remove(path)
        return jsonify({"success": True})
    return jsonify({"success": False})

@app.route("/download_excel")
def download_excel():
    trans = Transaction.query.all()
    df = pd.DataFrame([{
        "Date": t.date, "Customer": t.customer, "Mobile": t.mobile,
        "Total": t.total, "Paid": t.paid, "Balance": t.balance
    } for t in trans])
    path = "Transaction_Report.xlsx"
    df.to_excel(path, index=False)
    return send_file(path, as_attachment=True)

if __name__ == "__main__":
    app.run(debug=True)
   
      
