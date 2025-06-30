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
import tempfile
import gc

app = Flask(__name__)

GOOGLE_DRIVE_FILE_ID = os.getenv('GOOGLE_DRIVE_FILE_ID', '1K9yrMY-qJI5IjAQjrfZ_Odzos0cX0bt1')

def stream_folio_data(folio_number, file_id):
    """Stream through CSV file from Google Drive and return matching folio rows"""
    try:
        url = f"https://drive.google.com/uc?id={file_id}&export=download"
        response = requests.get(url, stream=True)
        response.raise_for_status()

        csv_stream = io.StringIO(response.content.decode('utf-8', errors='ignore'))
        chunks = pd.read_csv(csv_stream, chunksize=5000, dtype=str, low_memory=True)
        results = []

        for chunk in chunks:
            chunk = chunk.dropna(subset=['Folio'])
            filtered = chunk[chunk['Folio'].astype(str).str.strip() == folio_number]
            if not filtered.empty:
                results.append(filtered)

        return pd.concat(results).reset_index(drop=True) if results else pd.DataFrame()

    except Exception as e:
        print(f"[ERROR] Streaming folio data: {e}")
        return pd.DataFrame()

@app.route('/', methods=['GET', 'POST'])
def index():
    result = None
    error = None
    folio_number = ''
    total_records = 'N/A'

    if request.method == 'POST':
        folio_number = request.form.get('folio_number', '').strip()
        if not folio_number:
            error = "Please enter a folio number"
        else:
            try:
                folio_data = stream_folio_data(folio_number, GOOGLE_DRIVE_FILE_ID)

                if not folio_data.empty:
                    all_records = []
                    active_count = 0

                    folio_data['Status'] = folio_data['Status'].astype(str).str.strip().str.lower()

                    def map_status(status):
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
                        else:
                            return 'Unknown'

                    folio_data['Mapped_Status'] = folio_data['Status'].apply(map_status)

                    for _, record in folio_data.iterrows():
                        status = record.get('Mapped_Status', 'Unknown')
                        active_status = 'Active' if status == 'Live' else 'Inactive' if status in ['Terminated', 'Expired', 'Pending', 'Cancelled'] else 'Unknown'
                        if active_status == 'Active':
                            active_count += 1

                        record_dict = record.dropna().to_dict()
                        all_records.append({'status': active_status, 'details': record_dict})

                    overall_status = 'Active' if active_count > 0 else 'Inactive'
                    result = {
                        'folio_number': folio_number,
                        'status': overall_status,
                        'total_investments': len(all_records),
                        'active_investments': active_count,
                        'investments': all_records,
                        'details': all_records[0]['details'] if all_records else {}
                    }

                else:
                    error = f"Folio number '{folio_number}' not found"

            except Exception as e:
                print(f"Error during folio processing: {e}")
                error = "An unexpected error occurred while processing your request"

    return render_template('index.html',
                           result=result,
                           error=error,
                           folio_number=folio_number,
                           total_records=total_records)

@app.route('/download-folio-report/<folio_number>')
def download_folio_report(folio_number):
    try:
        folio_data = stream_folio_data(folio_number, GOOGLE_DRIVE_FILE_ID)
        if folio_data.empty:
            return render_template('400.html', error_message="Folio not found"), 404

        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
            doc = SimpleDocTemplate(tmp_file.name, pagesize=A4)
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

            folio_data['Status'] = folio_data['Status'].astype(str).str.strip().str.lower()

            def map_status(status):
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
                else:
                    return 'Unknown'

            folio_data['Mapped_Status'] = folio_data['Status'].apply(map_status)

            for idx, (_, record) in enumerate(folio_data.iterrows(), 1):
                status = record.get('Mapped_Status', 'Unknown')
                active_status = 'Active' if status == 'Live' else 'Inactive' if status in ['Terminated', 'Expired', 'Pending', 'Cancelled'] else 'Unknown'
                story.append(Paragraph(f"Investment #{idx}", styles['Heading3']))
                story.append(Spacer(1, 8))

                color = 'green' if active_status == 'Active' else 'red' if active_status == 'Inactive' else 'orange'
                story.append(Paragraph(f"Status: <font color=\"{color}\"><b>{active_status}</b></font>", styles['Normal']))
                story.append(Spacer(1, 8))

                clean_record = record.dropna()
                table_data = [['Field', 'Value']] + [
                    [str(k), str(v)] for k, v in clean_record.items() if str(v).strip()
                ]

                if len(table_data) > 1:
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
                if idx % 10 == 0:
                    gc.collect()

            story.append(Paragraph("Generated by Bajaj Capital Folio System", styles['Normal']))
            doc.build(story)
            del story
            gc.collect()

        return send_file(tmp_file.name,
                         mimetype='application/pdf',
                         as_attachment=True,
                         download_name=f'Folio_{folio_number}_Complete_Report.pdf')

    except Exception as e:
        print(f"Error generating PDF: {e}")
        gc.collect()
        return render_template('500.html', error_message="Error generating PDF"), 500

@app.errorhandler(400)
def bad_request(error):
    return render_template('400.html'), 400

@app.errorhandler(500)
def internal_error(error):
    gc.collect()
    return render_template('500.html'), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)
