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
import gc
from functools import lru_cache
import tempfile

app = Flask(__name__)

GOOGLE_DRIVE_FILE_ID = os.getenv(
    'GOOGLE_DRIVE_FILE_ID',
    '1K9yrMY-qJI5IjAQjrfZ_Odzos0cX0bt1'
)

CACHE_DURATION = 300  # seconds
_cached_data = None
_cache_timestamp = None

@lru_cache(maxsize=1)
def download_csv_from_drive(file_id):
    """Download CSV with chunked streaming and decode bytes to str."""
    try:
        url = f"https://drive.google.com/uc?id={file_id}"
        resp = requests.get(url, timeout=30, stream=True)
        resp.raise_for_status()

        chunks = []
        for chunk in resp.iter_content(chunk_size=8192):
            if chunk:
                chunks.append(chunk.decode('utf-8'))
        csv_text = ''.join(chunks)

        df = pd.read_csv(
            io.StringIO(csv_text),
            dtype=str,
            low_memory=True,
            engine='c'
        )

        del chunks, csv_text
        gc.collect()
        return df

    except Exception as e:
        print(f"Download error: {e}")
        return None

def preprocess_data(df_input):
    """Clean, dedupe, map status, optimize dtypes."""
    df = df_input.drop_duplicates().reset_index(drop=True)

    # Deduplicate on key columns
    keys = [c for c in ['Folio','Start Date','End Date','Amount','Scheme Name'] if c in df]
    if keys:
        df = df.drop_duplicates(subset=keys).reset_index(drop=True)

    # Status mapping
    if 'Status' in df:
        s = df['Status'].astype(str).str.strip().str.lower()
        conditions = [
            s.str.contains('live', na=False),
            s.str.contains('terminated|terminatied', na=False),
            s.str.contains('expired', na=False),
            s.str.contains('cancelled|rejection|rejected|incorrect|failure', na=False),
            s.str.contains('pause|pending|marked|registration|active', na=False),
        ]
        choices = ['Live','Terminated','Expired','Cancelled','Pending']
        df['Mapped_Status'] = pd.Series(
            pd.np.select(conditions, choices, default='Unknown'),
            index=df.index
        )

    # Frequency formatting
    if 'Frequency' in df:
        df['Frequency'] = df['Frequency'].astype(str).str.title()

    # Convert low-cardinality object columns to category
    for col in df.select_dtypes(include='object'):
        if df[col].nunique() / len(df) < 0.5:
            df[col] = df[col].astype('category')

    gc.collect()
    return df

def get_cached_data():
    global _cached_data, _cache_timestamp
    now = datetime.now().timestamp()
    if (_cached_data is None or 
        _cache_timestamp is None or 
        now - _cache_timestamp > CACHE_DURATION):
        raw = download_csv_from_drive(GOOGLE_DRIVE_FILE_ID)
        if raw is not None:
            _cached_data = preprocess_data(raw)
            _cache_timestamp = now
            del raw
            gc.collect()
    return _cached_data

def get_folio_data(folio, df):
    try:
        return df.query("Folio == @folio").copy()
    except:
        return df[df['Folio'].astype(str).str.strip() == folio].copy()

@app.route('/', methods=['GET','POST'])
def index():
    result = None
    error = None
    folio = ''
    total = 0

    if request.method == 'POST':
        folio = request.form.get('folio_number','').strip()
        if not folio:
            error = "Please enter a folio number"
        else:
            df = get_cached_data()
            if df is None:
                return render_template('500.html', error_message="Unable to load data"), 500

            total = len(df)
            data = get_folio_data(folio, df)
            if not data.empty:
                all_recs = []
                active = 0
                for _, r in data.iterrows():
                    status = r.get('Mapped_Status','Unknown')
                    st = 'Active' if status=='Live' else 'Inactive' if status in ['Terminated','Expired','Pending','Cancelled'] else 'Unknown'
                    if st=='Active': active+=1
                    rec = r.dropna().to_dict()
                    all_recs.append({'status': st, 'details': rec})
                overall = 'Active' if active>0 else 'Inactive'
                result = {
                    'folio_number': folio,
                    'status': overall,
                    'total_investments': len(all_recs),
                    'active_investments': active,
                    'investments': all_recs,
                    'details': all_recs[0]['details']
                }
            else:
                error = f"Folio '{folio}' not found"

    return render_template('index.html',
                           result=result,
                           error=error,
                           folio_number=folio,
                           total_records=total)

@app.route('/download-folio-report/<folio>')
def download_report(folio):
    df = get_cached_data()
    if df is None:
        return render_template('500.html', error_message="Unable to load data"), 500

    data = get_folio_data(folio, df)
    if data.empty:
        return render_template('400.html', error_message="Folio not found"), 404

    try:
        # Write PDF to temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp:
            doc = SimpleDocTemplate(tmp.name, pagesize=A4)
            styles = getSampleStyleSheet()
            story = []

            story.append(Paragraph("Comprehensive Folio Status Report", styles['Title']))
            story.append(Spacer(1,20))
            story.append(Paragraph("Bajaj Capital", styles['Heading2']))
            story.append(Spacer(1,12))
            story.append(Paragraph(f"""
                Report Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}<br/>
                Folio Number: {folio}<br/>
                Total Investments: {len(data)}
            """, styles['Normal']))
            story.append(Spacer(1,20))

            for i, (_, r) in enumerate(data.iterrows(), 1):
                status = r.get('Mapped_Status','Unknown')
                st = 'Active' if status=='Live' else 'Inactive' if status in ['Terminated','Expired','Pending','Cancelled'] else 'Unknown'
                story.append(Paragraph(f"Investment #{i}", styles['Heading3']))
                story.append(Spacer(1,8))
                color = 'green' if st=='Active' else 'red' if st=='Inactive' else 'orange'
                story.append(Paragraph(f"Status: <font color=\"{color}\"><b>{st}</b></font>", styles['Normal']))
                story.append(Spacer(1,8))

                row = r.dropna()
                table_data = [['Field','Value']] + [[str(k),str(v)] for k,v in row.items() if str(v).strip()]
                if len(table_data)>1:
                    tbl = Table(table_data)
                    tbl.setStyle(TableStyle([
                        ('BACKGROUND',(0,0),(-1,0),colors.grey),
                        ('TEXTCOLOR',(0,0),(-1,0),colors.whitesmoke),
                        ('ALIGN',(0,0),(-1,-1),'LEFT'),
                        ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),
                        ('FONTSIZE',(0,0),(-1,0),10),
                        ('BOTTOMPADDING',(0,0),(-1,0),8),
                        ('BACKGROUND',(0,1),(-1,-1),colors.beige),
                        ('GRID',(0,0),(-1,-1),1,colors.black),
                        ('FONTSIZE',(0,1),(-1,-1),8),
                    ]))
                    story.append(tbl)
                story.append(Spacer(1,15))
                if i%10==0: gc.collect()

            story.append(Paragraph("Generated by Bajaj Capital Folio System", styles['Normal']))
            doc.build(story)
            del story; gc.collect()

        # Serve file
        return send_file(tmp.name,
                         mimetype='application/pdf',
                         as_attachment=True,
                         download_name=f'Folio_{folio}_Report.pdf')
    except Exception as e:
        print(f"PDF error: {e}")
        gc.collect()
        return render_template('500.html', error_message="Error generating PDF"), 500

@app.errorhandler(400)
def bad_request(e):
    return render_template('400.html'), 400

@app.errorhandler(500)
def internal_error(e):
    gc.collect()
    return render_template('500.html'), 500

@app.before_request
def cleanup_cache():
    """Purge cache if too old."""
    global _cached_data, _cache_timestamp
    if _cache_timestamp and datetime.now().timestamp() - _cache_timestamp > CACHE_DURATION*2:
        _cached_data = None
        _cache_timestamp = None
        gc.collect()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)
