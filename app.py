from flask import Flask, render_template, request, send_file
import os
import pandas as pd
from datetime import datetime
import gdown
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
import tempfile
import gc

app = Flask(__name__)

CSV_FILE_ID = '1K9yrMY-qJI5IjAQjrfZ_Odzos0cX0bt1'
CSV_FILENAME = 'folio_data.csv'
ESSENTIAL_COLUMNS = ['Folio', 'Status', 'AC_HOLDER_', 'TO_DATE', 'CEASE_DATE', 'AUTO_AMOUN']

def download_csv_if_not_exists():
    if not os.path.exists(CSV_FILENAME):
        print("Downloading CSV file...")
        url = f"https://drive.google.com/uc?id={CSV_FILE_ID}"
        gdown.download(url, CSV_FILENAME, quiet=False)

def map_status(status):
    status = str(status).strip().lower()
    if 'live' in status:
        return 'Live'
    elif 'terminated' in status or 'terminatied' in status:
        return 'Terminated'
    elif 'expired' in status:
        return 'Expired'
    elif any(k in status for k in ['cancelled', 'rejection', 'rejected', 'incorrect', 'failure']):
        return 'Cancelled'
    elif any(k in status for k in ['pause', 'pending', 'marked', 'registration', 'active']):
        return 'Pending'
    return 'Unknown'

@app.route('/', methods=['GET', 'POST'])
def index():
    result = None
    error = None
    folio_number = ""

    download_csv_if_not_exists()

    if request.method == 'POST':
        folio_number = request.form.get('folio_number', '').strip()

        if not folio_number:
            error = "Please enter a folio number"
        else:
            try:
                df = pd.read_csv(CSV_FILENAME, usecols=ESSENTIAL_COLUMNS, dtype=str, low_memory=False)
                df['Folio'] = df['Folio'].astype(str).str.strip()
                filtered = df[df['Folio'] == folio_number]

                if filtered.empty:
                    error = f"No records found for folio number: {folio_number}"
                else:
                    filtered['Mapped_Status'] = filtered['Status'].apply(map_status)
                    records = []
                    active_count = 0

                    for _, rec in filtered.iterrows():
                        status = rec['Mapped_Status']
                        active = 'Active' if status == 'Live' else 'Inactive'
                        if active == 'Active':
                            active_count += 1
                        records.append({
                            'Bank': rec.get('AC_HOLDER_', ''),
                            'Amount': rec.get('AUTO_AMOUN', ''),
                            'Status': active,
                            'TO_DATE': rec.get('TO_DATE', ''),
                            'CEASE_DATE': rec.get('CEASE_DATE', '')
                        })

                    result = {
                        'folio_number': folio_number,
                        'overall_status': 'Active' if active_count > 0 else 'Inactive',
                        'total': len(records),
                        'active': active_count,
                        'records': records
                    }

            except Exception as e:
                error = f"Error while processing data: {e}"

    return render_template('index.html', result=result, error=error, folio_number=folio_number)

@app.route('/download-folio-report/<folio_number>')
def download_folio_report(folio_number):
    try:
        download_csv_if_not_exists()

        df = pd.read_csv(CSV_FILENAME, usecols=ESSENTIAL_COLUMNS, dtype=str, low_memory=False)
        df['Folio'] = df['Folio'].astype(str).str.strip()
        filtered = df[df['Folio'] == folio_number]

        if filtered.empty:
            return f"No records found for folio number: {folio_number}", 404

        filtered['Mapped_Status'] = filtered['Status'].apply(map_status)

        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
            doc = SimpleDocTemplate(tmp_file.name, pagesize=A4)
            styles = getSampleStyleSheet()
            story = []

            story.append(Paragraph("Folio Report", styles['Title']))
            story.append(Spacer(1, 20))
            story.append(Paragraph(f"Folio Number: {folio_number}", styles['Heading2']))
            story.append(Paragraph(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['Normal']))
            story.append(Spacer(1, 15))

            for i, (_, rec) in enumerate(filtered.iterrows(), 1):
                status = rec['Mapped_Status']
                active = 'Active' if status == 'Live' else 'Inactive'

                story.append(Paragraph(f"Investment #{i}", styles['Heading3']))
                story.append(Paragraph(f"Status: <font color='{'green' if active=='Active' else 'red'}'><b>{active}</b></font>", styles['Normal']))
                story.append(Spacer(1, 6))

                table_data = [['Field', 'Value']]
                for col in ESSENTIAL_COLUMNS:
                    val = rec.get(col, '')
                    if pd.notna(val):
                        table_data.append([col, str(val)])

                table = Table(table_data)
                table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, 0), 10),
                    ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
                    ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                    ('GRID', (0, 0), (-1, -1), 1, colors.black),
                    ('FONTSIZE', (0, 1), (-1, -1), 8),
                ]))
                story.append(table)
                story.append(Spacer(1, 15))

            doc.build(story)
            return send_file(tmp_file.name,
                             mimetype='application/pdf',
                             as_attachment=True,
                             download_name=f'Folio_{folio_number}_Report.pdf')

    except Exception as e:
        print("Error generating PDF:", e)
        gc.collect()
        return "Error generating report", 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)

