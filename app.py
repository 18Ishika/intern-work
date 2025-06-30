from flask import Flask, request, render_template, send_file
import os
import pandas as pd
import io
import requests
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors

app = Flask(__name__)

GOOGLE_DRIVE_FILE_ID = os.getenv('GOOGLE_DRIVE_FILE_ID', '1K9yrMY-qJI5IjAQjrfZ_Odzos0cX0bt1')

def download_csv_from_drive(file_id):
    try:
        download_url = f"https://drive.google.com/uc?id={file_id}"
        response = requests.get(download_url, timeout=30)
        response.raise_for_status()
        csv_data = pd.read_csv(io.StringIO(response.text))
        return csv_data
    except Exception as e:
        print(f"Download error: {e}")
        return None

def preprocess_data(df_input):
    df = df_input.copy().drop_duplicates().reset_index(drop=True)
    key_cols = [col for col in ['Folio', 'Start Date', 'End Date', 'Amount', 'Scheme Name'] if col in df.columns]
    if key_cols:
        df = df.drop_duplicates(subset=key_cols).reset_index(drop=True)

    if 'Status' in df.columns:
        df['Status'] = df['Status'].astype(str).str.strip().str.lower()
        def map_status(s):
            if 'live' in s: return 'Live'
            elif 'terminated' in s or 'terminatied' in s: return 'Terminated'
            elif 'expired' in s: return 'Expired'
            elif any(x in s for x in ['cancelled', 'rejection', 'rejected', 'incorrect', 'failure']): return 'Cancelled'
            elif any(x in s for x in ['pause', 'pending', 'marked', 'registration', 'active']): return 'Pending'
            else: return 'Unknown'
        df['Mapped_Status'] = df['Status'].apply(map_status)

    if 'Frequency' in df.columns:
        df['Frequency'] = df['Frequency'].astype(str).str.title()

    return df

@app.route('/', methods=['GET', 'POST'])
def index():
    result = None
    error = None
    folio_number = ''
    total_records = 0

    if request.method == 'POST':
        folio_number = request.form.get('folio_number', '').strip()
        if not folio_number:
            error = "Please enter a folio number"
        else:
            csv_data = download_csv_from_drive(GOOGLE_DRIVE_FILE_ID)
            if csv_data is None:
                return render_template('500.html', error_message="Unable to load data from Google Drive."), 500

            df = preprocess_data(csv_data)
            total_records = len(df)
            folio_data = df[df['Folio'].astype(str).str.strip() == folio_number]

            if not folio_data.empty:
                all_records = []
                active_count = 0

                for _, record in folio_data.iterrows():
                    status = record.get('Mapped_Status', 'Unknown')
                    active_status = 'Active' if status == 'Live' else 'Inactive' if status in ['Terminated', 'Expired', 'Pending', 'Cancelled'] else 'Unknown'
                    if active_status == 'Active':
                        active_count += 1
                    all_records.append({'status': active_status, 'details': record.to_dict()})

                overall_status = 'Active' if active_count > 0 else 'Inactive'
                result = {
                    'folio_number': folio_number,
                    'status': overall_status,
                    'total_investments': len(all_records),
                    'active_investments': active_count,
                    'investments': all_records,
                    'details': all_records[0]['details']
                }
            else:
                error = f"Folio number '{folio_number}' not found"

    return render_template('index.html',
                           result=result,
                           error=error,
                           folio_number=folio_number,
                           total_records=total_records)

@app.route('/download-folio-report/<folio_number>')
def download_folio_report(folio_number):
    csv_data = download_csv_from_drive(GOOGLE_DRIVE_FILE_ID)
    if csv_data is None:
        return render_template('500.html', error_message="Unable to load data."), 500

    df = preprocess_data(csv_data)
    folio_data = df[df['Folio'].astype(str).str.strip() == folio_number]

    if folio_data.empty:
        return render_template('400.html', error_message="Folio not found"), 404

    try:
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        styles = getSampleStyleSheet()
        story = []

        story.append(Paragraph("Comprehensive Folio Status Report", styles['Title']))
        story.append(Spacer(1, 20))
        story.append(Paragraph("Bajaj Capital", styles['Heading2']))
        story.append(Spacer(1, 12))
        story.append(Paragraph(f"""
            Report Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}<br/>
            Folio Number: {folio_number}<br/>
            Total Investments: {len(folio_data)}
        """, styles['Normal']))
        story.append(Spacer(1, 20))

        for idx, (_, record) in enumerate(folio_data.iterrows(), 1):
            status = record.get('Mapped_Status', 'Unknown')
            active_status = 'Active' if status == 'Live' else 'Inactive' if status in ['Terminated', 'Expired', 'Pending', 'Cancelled'] else 'Unknown'
            story.append(Paragraph(f"Investment #{idx}", styles['Heading3']))
            story.append(Spacer(1, 8))
            color = 'green' if active_status == 'Active' else 'red' if active_status == 'Inactive' else 'orange'
            story.append(Paragraph(f"Status: <font color=\"{color}\"><b>{active_status}</b></font>", styles['Normal']))
            story.append(Spacer(1, 8))

            table_data = [['Field', 'Value']] + [[str(k), str(v)] for k, v in record.items() if pd.notna(v) and str(v).strip()]
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

        story.append(Paragraph("Generated by Bajaj Capital Folio System", styles['Normal']))
        doc.build(story)
        buffer.seek(0)

        return send_file(buffer,
                         mimetype='application/pdf',
                         as_attachment=True,
                         download_name=f'Folio_{folio_number}_Complete_Report.pdf')
    except Exception as e:
        print(f"Error generating PDF: {e}")
        return render_template('500.html', error_message="Error generating PDF"), 500

@app.errorhandler(400)
def bad_request(error):
    return render_template('400.html'), 400

@app.errorhandler(500)
def internal_error(error):
    return render_template('500.html'), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)
