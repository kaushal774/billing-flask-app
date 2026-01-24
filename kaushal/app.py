from flask import Flask, render_template, request, send_file, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from models import db, ShopProfile, Inventory, BillRecord
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from datetime import datetime
import os

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///jewellery_pro.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

BILL_FOLDER = "generated_bills"
os.makedirs(BILL_FOLDER, exist_ok=True)

with app.app_context():
    db.create_all()
    if not ShopProfile.query.first():
        db.session.add(ShopProfile())
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
        net_weight = float(request.form.get("net_weight") or 0)
        old_weight = float(request.form.get("old_weight") or 0)
        math_rate = float(request.form.get("math_rate") or 0)
        display_rate = request.form.get("display_rate") or "0"
        making = float(request.form.get("making") or 0)
        extra_adj = float(request.form.get("extra_adj") or 0)
        gst_per = float(request.form.get("gst_per") or 0)
        discount = float(request.form.get("discount") or 0)
        paid = float(request.form.get("paid_amount") or 0)

        item_names = request.form.getlist("item_name[]")
        item_weights = request.form.getlist("item_weight[]")
        purchased_items = []
        
        for n, w in zip(item_names, item_weights):
            if n and w:
                weight_val = float(w)
                purchased_items.append((n, weight_val))
                stock_item = Inventory.query.filter_by(metal=metal, item_name=n).first()
                if stock_item:
                    stock_item.weight = round(max(0, stock_item.weight - weight_val), 3)

        billing_w = net_weight - old_weight
        if metal == "Gold":
            purity_val = float(request.form.get("purity", 75))
            base_val = (math_rate / 10) * billing_w
            metal_amt = base_val * (purity_val / 100)
            making_amt = base_val * ((making + extra_adj) / 100)
            purity_label = f"Gold {purity_val}%"
        else:
            metal_amt = (math_rate / 1000) * billing_w
            making_amt = making + (metal_amt * (extra_adj / 100))
            purity_label = "Silver"

        gst_amt = (metal_amt + making_amt) * (gst_per / 100)
        total_final = round(max(0, metal_amt + making_amt + gst_amt - discount), 2)
        balance = round(total_final - paid, 2)
        
        db.session.add(BillRecord(date=datetime.now().strftime("%d-%m-%Y"), customer=customer, total=total_final, balance=balance))
        db.session.commit()

        bill_data = {
            "Date": datetime.now().strftime("%d-%m-%Y"),
            "Customer": customer, "Mobile": mobile, "Metal": metal,
            "NetW": net_weight, "OldW": old_weight, "Purity": purity_label,
            "Rate": display_rate, "Gst": round(gst_amt, 2), "Total": total_final,
            "Paid": paid, "Balance": balance, "Discount": discount,
            "Items": "|".join([f"{n}:{w}" for n, w in purchased_items])
        }

    return render_template("bill.html", bill=bill_data, shop=shop, gold_list=gold_items, silver_list=silver_items)

@app.route("/admin", methods=["GET", "POST"])
def admin():
    shop = ShopProfile.query.first()
    inventory = Inventory.query.all()
    if request.method == "POST":
        if 'update_shop' in request.form:
            shop.name, shop.gst, shop.address, shop.mobile = request.form['name'], request.form['gst'], request.form['address'], request.form['mobile']
        elif 'add_stock' in request.form:
            m, n, w = request.form['metal'], request.form['item_name'].upper(), float(request.form['weight'])
            item = Inventory.query.filter_by(metal=m, item_name=n).first()
            if item: item.weight += w
            else: db.session.add(Inventory(metal=m, item_name=n, weight=w))
        db.session.commit()
        return redirect(url_for('admin'))
    return render_template("admin.html", shop=shop, inventory=inventory)
@app.route("/pdf", methods=["POST"])
def generate_pdf():
    shop = ShopProfile.query.first()
    data = request.form
    customer = data.get("Customer", "Customer")
    filename = os.path.join(BILL_FOLDER, f"Bill_{customer}.pdf")
    
    # --- CALCULATIONS FOR PDF DISPLAY ---
    try:
        total = float(data.get('Total') or 0)
        gst = float(data.get('Gst') or 0)
        # Handle Rate (removing commas if present)
        rate_val = float(str(data.get('Rate')).replace(',', '') if data.get('Rate') else 0)
        net_w = float(data.get('NetW') or 0)
        old_w = float(data.get('OldW') or 0)
        discount = float(data.get('Discount') or 0)
        
        # YOUR UPDATED FORMULA: Making = Total - GST - (Rate * (NetW - OldW) / 10) + Discount
        billing_w = net_w - old_w
        making_calc = total - gst - (rate_val * billing_w / 10) + discount
        making_display = f"{round(making_calc, 2)}"
    except Exception as e:
        making_display = "0.00"

    # --- PURITY CARAT MAPPING ---
    purity_raw = data.get('Purity', '')
    if '75' in purity_raw: carat = "18K"
    elif '84' in purity_raw: carat = "20K"
    elif '92' in purity_raw: carat = "22K"
    else: carat = purity_raw # Falls back to Silver or other text

    doc = SimpleDocTemplate(filename, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = []

    # --- Header (Professional Branding) ---
    elements.append(Paragraph(f"<b>{shop.name}</b>", styles['Title']))
    elements.append(Paragraph(f"{shop.address}<br/>GST: {shop.gst} | Mob: {shop.mobile}", styles['Normal']))
    elements.append(Spacer(1, 15))

    # --- Customer & Bill Info ---
    cust_info = [
        [f"Customer: {data.get('Customer')}", f"Date: {data.get('Date')}"],
        [f"Mobile: {data.get('Mobile')}", f"Metal: {data.get('Metal')} ({carat})"]
    ]
    t_cust = Table(cust_info, colWidths=[240, 200])
    t_cust.setStyle(TableStyle([('LINEBELOW', (0,1), (-1,1), 1, colors.black)]))
    elements.append(t_cust)
    elements.append(Spacer(1, 15))

    # --- Items Table ---
    item_data = [["Item Description", "Weight (gm)"]]
    for entry in data.get("Items", "").split("|"):
        if ":" in entry: item_data.append(entry.split(":"))
    
    t_items = Table(item_data, colWidths=[340, 100])
    t_items.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
        ('ALIGN', (1,0), (1,-1), 'CENTER')
    ]))
    elements.append(Paragraph("<b>Purchase Details:</b>", styles['Heading4']))
    elements.append(t_items)
    elements.append(Spacer(1, 20))

    # --- Calculation Summary (Applying your specific display logic) ---
    summary_data = [
        ["Net Weight:", f"{net_w} g", "Applied Rate:", f"Rs. {data.get('Rate')}"],
        ["Old Weight:", f"- {old_w} g", "GST Amount:", f"Rs. {data.get('Gst')}"],
        ["Discount:", f"- Rs. {discount}", "Making Charges:", f"Rs. {making_display}"],
        ["", "", "", ""], 
        ["TOTAL AMOUNT:", f"Rs. {total}", "PAID:", f"Rs. {data.get('Paid')}"],
        ["", "", "BALANCE DUE:", f"Rs. {data.get('Balance')}"]
    ]

    t_summary = Table(summary_data, colWidths=[110, 110, 110, 110])
    t_summary.setStyle(TableStyle([
        ('GRID', (0,0), (-1,2), 0.5, colors.grey),
        ('FONTNAME', (0,4), (-1,5), 'Helvetica-Bold'),
        ('TEXTCOLOR', (3,5), (3,5), colors.red),
        ('BACKGROUND', (2,4), (3,5), colors.whitesmoke)
    ]))
    elements.append(t_summary)
    
    elements.append(Spacer(1, 60))
    elements.append(Paragraph("__________________________", styles['Normal']))
    elements.append(Paragraph("Authorized Signatory", styles['Normal']))

    doc.build(elements)
    return send_file(filename, as_attachment=True)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)