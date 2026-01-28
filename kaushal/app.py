from flask import Flask, render_template, request, send_file, redirect, url_for, send_from_directory, jsonify
from flask_sqlalchemy import SQLAlchemy
from models import db, ShopProfile, Inventory
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
# Added Image for spacing and PageBreak if needed, though SimpleDocTemplate is fine
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from datetime import datetime
import os
import pandas as pd
import shutil

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///jewellery_pro.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

# Folder and File Paths
BILL_FOLDER = "generated_bills"
EXCEL_FILE = "transaction_records.xlsx"
BACKUP_FOLDER = "backups"

os.makedirs(BILL_FOLDER, exist_ok=True)
os.makedirs(BACKUP_FOLDER, exist_ok=True)

# --- SHOP DETAILS CONFIGURATION ---
with app.app_context():
    db.create_all()
    shop = ShopProfile.query.first()
    if not shop:
        shop = ShopProfile(name="My Jewellery Shop", address="Update Address")
        db.session.add(shop)
    
    # EDIT THESE LINES TO CHANGE YOUR SHOP DETAILS
    shop.name = "Fakkad Jewellers"
    shop.gst = "09BMRPS8447R1Z1"
    shop.address = "KHUNNI GHEE WALE KE BAGAL ME,MADHOGARH,JALAUN(UP)"
    shop.mobile = "9451508591"
    
    db.session.commit()

def log_to_excel(data):
    new_row = {
        "Date": data["Date"], "Customer": data["Customer"], "Mobile": data["Mobile"],
        "Metal": data["Metal"], "Items": data["Items"], "Net_Weight": data["NetW"],
        "Old_Weight": data["OldW"], "Total_Amount": data["Total"],
        "Paid_Amount": data["Paid"], "Balance_Due": data["Balance"]
    }
    df_new = pd.DataFrame([new_row])
    try:
        if not os.path.exists(EXCEL_FILE):
            df_new.to_excel(EXCEL_FILE, index=False)
        else:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            shutil.copy(EXCEL_FILE, os.path.join(BACKUP_FOLDER, f"backup_{ts}.xlsx"))
            df_existing = pd.read_excel(EXCEL_FILE)
            df_final = pd.concat([df_existing, df_new], ignore_index=True)
            df_final.to_excel(EXCEL_FILE, index=False)
            all_backups = sorted([os.path.join(BACKUP_FOLDER, f) for f in os.listdir(BACKUP_FOLDER)])
            if len(all_backups) > 20: os.remove(all_backups[0])
    except Exception as e:
        with open("emergency_save_log.txt", "a") as f:
            f.write(f"\n{datetime.now()} - {new_row} - Error: {e}")

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
            p_label = f"Gold {purity}%"
            sub_total = m_amt + mk_amt
            total_with_gst = sub_total + (sub_total * (gst_p / 100))
            total = total_with_gst * 1.002911 
        else:
            m_amt = (math_r / 1000) * billing_w
            mk_amt = making + (m_amt * (extra_adj / 100))
            p_label = "Silver"
            sub_total = m_amt + mk_amt
            total = sub_total + (sub_total * (gst_p / 100))

        final_total = round(max(0, total - disc), 2)
        gst_final = round((sub_total * (gst_p / 100)), 2)
        
        db.session.commit()
        bill_data = {
            "Date": datetime.now().strftime("%d-%m-%Y"), "Customer": customer, "Mobile": mobile, 
            "Metal": metal, "NetW": net_w, "OldW": old_w, "Purity": p_label,
            "Rate": display_rate, "Gst": gst_final, "Making_Input": making,
            "Total": final_total, "Paid": paid, "Balance": round(final_total - paid, 2), "Discount": disc,
            "Items": "|".join([f"{n}:{w}" for n, w in purchased_items])
        }
        log_to_excel(bill_data)

    return render_template("bill.html", bill=bill_data, shop=shop, gold_list=gold_items, silver_list=silver_items)

@app.route("/records")
def view_records():
    if not os.path.exists(EXCEL_FILE): return "No records found yet."
    df = pd.read_excel(EXCEL_FILE)
    table_html = df.to_html(classes='table table-striped table-hover table-bordered', index=True, table_id="recordTable")
    return render_template("records.html", table=table_html)

@app.route("/delete_record/<int:row_index>", methods=["POST"])
def delete_record(row_index):
    try:
        if not os.path.exists(EXCEL_FILE): return jsonify({"success": False}), 404
        df = pd.read_excel(EXCEL_FILE)
        if 0 <= row_index < len(df):
            df = df.drop(df.index[row_index])
            df.to_excel(EXCEL_FILE, index=False)
            return jsonify({"success": True}), 200
        return jsonify({"success": False}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/bill_gallery")
def bill_gallery():
    if not os.path.exists(BILL_FOLDER): os.makedirs(BILL_FOLDER)
    files = [f for f in os.listdir(BILL_FOLDER) if f.endswith('.pdf')]
    files.sort(key=lambda x: os.path.getmtime(os.path.join(BILL_FOLDER, x)), reverse=True)
    return render_template("gallery.html", files=files)

@app.route("/view_pdf/<filename>")
def view_pdf(filename):
    return send_from_directory(BILL_FOLDER, filename)

@app.route("/delete_pdf", methods=["POST"])
def delete_pdf():
    try:
        data = request.get_json()
        filename = data.get('filename')
        file_path = os.path.join(BILL_FOLDER, filename)
        if os.path.exists(file_path):
            os.remove(file_path)
            return jsonify({"success": True}), 200
        return jsonify({"success": False}), 404
    except Exception:
        return jsonify({"success": False}), 500

@app.route("/admin", methods=["GET", "POST"])
def admin():
    shop = ShopProfile.query.first()
    inventory = Inventory.query.all()
    if request.method == "POST":
        if 'add_stock' in request.form:
            m, n, w = request.form['metal'], request.form['item_name'].upper(), float(request.form['weight'])
            item = Inventory.query.filter_by(metal=m, item_name=n).first()
            if item: item.weight += w
            else: db.session.add(Inventory(metal=m, item_name=n, weight=w))
        db.session.commit()
        return redirect(url_for('admin'))
    return render_template("admin.html", shop=shop, inventory=inventory)

@app.route("/pdf", methods=["POST"])
def generate_pdf():
    shop, data = ShopProfile.query.first(), request.form
    filename = os.path.join(BILL_FOLDER, f"Bill_{data.get('Customer')}.pdf")
    doc = SimpleDocTemplate(filename, pagesize=A4)
    styles = getSampleStyleSheet()
    
    t_val = float(data.get('Total', 0))
    r_val = float(data.get('Rate', 0)) 
    nw_val = float(data.get('NetW', 0))
    ow_val = float(data.get('OldW', 0))
    gst_val = float(data.get('Gst', 0))
    dsc_val = float(data.get('Discount', 0))
    # Extracting Balance and Paid amount
    paid_val = float(data.get('Paid', 0))
    balance_val = float(data.get('Balance', 0))
    metal_type = data.get('Metal')

    if metal_type == "Gold":
        metal_value = r_val * ((nw_val - ow_val) / 10)
        calc_making = round(t_val - gst_val - metal_value + dsc_val, 2)
    else:
        calc_making = float(data.get('Making_Input', 0))

    elements = [
        Paragraph(f"<b>{shop.name}</b>", styles['Title']),
        Paragraph(f"{shop.address}<br/>GST: {shop.gst} | Mob: {shop.mobile}", styles['Normal']),
        Spacer(1, 15)
    ]

    cust_info = [[f"Customer: {data.get('Customer')}", f"Date: {data.get('Date')}"], [f"Mobile: {data.get('Mobile')}", f"Metal: {metal_type}"]]
    t_cust = Table(cust_info, colWidths=[240, 200])
    t_cust.setStyle(TableStyle([('LINEBELOW', (0,1), (-1,1), 1, colors.black)]))
    elements.extend([t_cust, Spacer(1, 15)])

    item_data = [["Item", "Weight (g)"]]
    for entry in data.get("Items", "").split("|"):
        if ":" in entry: item_data.append(entry.split(":"))
    
    t_items = Table(item_data, colWidths=[340, 100])
    t_items.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), colors.lightgrey), ('GRID', (0,0), (-1,-1), 0.5, colors.grey)]))
    elements.extend([t_items, Spacer(1, 20)])

    # UPDATED: Added row for Balance Due
    summary_data = [
        ["Net Weight:", f"{nw_val} g", "Rate Applied:", f"Rs. {r_val}"],
        ["Old Weight:", f"- {ow_val} g", "Making Chrg:", f"Rs. {calc_making}"],
        ["Discount:", f"- Rs. {dsc_val}", "GST:", f"Rs. {gst_val}"],
        ["PAID:", f"Rs. {paid_val}", "TOTAL:", f"Rs. {t_val}"],
        ["", "", "BALANCE DUE:", f"Rs. {balance_val}"]
    ]
    t_summary = Table(summary_data, colWidths=[110, 110, 110, 110])
    # Adjusted style grid to include the 5th row
    t_summary.setStyle(TableStyle([
        ('GRID', (0,0), (-1,4), 0.5, colors.grey), 
        ('FONTNAME', (0,3), (-1,4), 'Helvetica-Bold')
    ]))
    elements.append(t_summary)
    
    doc.build(elements)
    return send_file(filename, as_attachment=True)

@app.route("/download_excel")
def download_excel():
    if os.path.exists(EXCEL_FILE): return send_file(EXCEL_FILE, as_attachment=True)
    return "No records."

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)