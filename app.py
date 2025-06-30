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

GOOGLE_DRIVE_FILE_ID = os.getenv('GOOGLE_DRIVE_FILE_ID', '1K9yrMY-qJI5IjAQjrfZ_Odzos0cX0bt1')

# Cache for storing preprocessed data (with TTL-like behavior)
_cached_data = None
_cache_timestamp = None
CACHE_DURATION = 300  # 5 minutes

@lru_cache(maxsize=1)
def download_csv_from_drive(file_id):
    """Download CSV with caching and memory optimization"""
    try:
        download_url = f"https://drive.google.com/uc?id={file_id}"
        response = requests.get(download_url, timeout=30, stream=True)
        response.raise_for_status()
        
        # Use chunked reading to avoid loading entire file into memory at once
        chunks = []
        for chunk in response.iter_content(chunk_size=8192, decode_unicode=True):
            if chunk:
                chunks.append(chunk)
        
        csv_content = ''.join(chunks)
        
        # Read CSV with memory-efficient options
        csv_data = pd.read_csv(
            io.StringIO(csv_content),
            dtype=str,  # Read all as strings initially to save memory
            low_memory=True,
            engine='c'  # Use faster C engine
        )
        
        # Clean up
        del chunks, csv_content
        gc.collect()
        
        return csv_data
    except Exception as e:
        print(f"Download error: {e}")
        return None

def get_cached_data():
    """Get cached data or refresh if expired"""
    global _cached_data, _cache_timestamp
    
    current_time = datetime.now().timestamp()
    
    if (_cached_data is None or 
        _cache_timestamp is None or 
        current_time - _cache_timestamp > CACHE_DURATION):
        
        # Clear old cache
        if _cached_data is not None:
            del _cached_data
            gc.collect()
        
        # Download and preprocess new data
        raw_data = download_csv_from_drive(GOOGLE_DRIVE_FILE_ID)
        if raw_data is not None:
            _cached_data = preprocess_data(raw_data)
            _cache_timestamp = current_time
            del raw_data  # Clean up raw data
            gc.collect()
    
    return _cached_data

def preprocess_data(df_input):
    """Optimized preprocessing with memory management"""
    # Work on a copy but be memory conscious
    df = df_input.copy()
    
    # Drop duplicates early to reduce memory footprint
    initial_len = len(df)
    df = df.drop_duplicates().reset_index(drop=True)
    print(f"Removed {initial_len - len(df)} duplicate rows")
    
    # Key columns deduplication
    key_cols = [col for col in ['Folio', 'Start Date', 'End Date', 'Amount', 'Scheme Name'] 
                if col in df.columns]
    if key_cols:
        df = df.drop_duplicates(subset=key_cols).reset_index(drop=True)

    # Status mapping with memory efficiency
    if 'Status' in df.columns:
        df['Status'] = df['Status'].astype(str).str.strip().str.lower()
        
        def map_status_vectorized(status_series):
            """Vectorized status mapping for better performance"""
            conditions = [
                status_series.str.contains('live', na=False),
                status_series.str.contains('terminated|terminatied', na=False),
                status_series.str.contains('expired', na=False),
                status_series.str.contains('cancelled|rejection|rejected|incorrect|failure', na=False),
                status_series.str.contains('pause|pending|marked|registration|active', na=False)
            ]
            choices = ['Live', 'Terminated', 'Expired', 'Cancelled', 'Pending']
            
            return pd.Series(
                pd.np.select(conditions, choices, default='Unknown'),
                index=status_series.index
            )
        
        df['Mapped_Status'] = map_status_vectorized(df['Status'])

    # Frequency processing
    if 'Frequency' in df.columns:
        df['Frequency'] = df['Frequency'].astype(str).str.title()

    # Optimize data types to save memory
    for col in df.columns:
        if df[col].dtype == 'object':
            try:
                # Try to convert to category if it has repeated values
                if df[col].nunique() / len(df) < 0.5:  # Less than 50% unique values
                    df[col] = df[col].astype('category')
            except:
                pass
    
    # Force garbage collection
    gc.collect()
    
    return df

def get_folio_data(folio_number, df):
    """Memory-efficient folio data extraction"""
    # Use query method which is more memory efficient for large datasets
    try:
        folio_data = df.query(f"Folio == '{folio_number}'").copy()
    except:
        # Fallback to traditional method
        folio_data = df[df['Folio'].astype(str).str.strip() == folio_number].copy()
    
    return folio_data

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
            try:
                df = get_cached_data()
                if df is None:
                    return render_template('500.html', 
                                         error_message="Unable to load data from Google Drive."), 500

                total_records = len(df)
                folio_data = get_folio_data(folio_number, df)

                if not folio_data.empty:
                    all_records = []
                    active_count = 0

                    # Process records in smaller batches to manage memory
                    for _, record in folio_data.iterrows():
                        status = record.get('Mapped_Status', 'Unknown')
                        active_status = ('Active' if status == 'Live' 
                                       else 'Inactive' if status in ['Terminated', 'Expired', 'Pending', 'Cancelled'] 
                                       else 'Unknown')
                        
                        if active_status == 'Active':
                            active_count += 1
                        
                        # Convert to dict and clean up NaN values to save memory
                        record_dict = record.dropna().to_dict()
                        all_records.append({
                            'status': active_status, 
                            'details': record_dict
                        })

                    overall_status = 'Active' if active_count > 0 else 'Inactive'
                    result = {
                        'folio_number': folio_number,
                        'status': overall_status,
                        'total_investments': len(all_records),
                        'active_investments': active_count,
                        'investments': all_records,
                        'details': all_records[0]['details'] if all_records else {}
                    }
                    
                    # Clean up
                    del folio_data, all_records
                    gc.collect()
                    
                else:
                    error = f"Folio number '{folio_number}' not found"
                    
            except Exception as e:
                print(f"Error processing request: {e}")
                error = "An error occurred while processing your request"
                gc.collect()  # Clean up on error

    return render_template('index.html',
                           result=result,
                           error=error,
                           folio_number=folio_number,
                           total_records=total_records)

@app.route('/download-folio-report/<folio_number>')
def download_folio_report(folio_number):
    try:
        df = get_cached_data()
        if df is None:
            return render_template('500.html', error_message="Unable to load data."), 500

        folio_data = get_folio_data(folio_number, df)

        if folio_data.empty:
            return render_template('400.html', error_message="Folio not found"), 404

        # Use temporary file to avoid keeping large PDF in memory
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
            doc = SimpleDocTemplate(tmp_file.name, pagesize=A4)
            styles = getSampleStyleSheet()
            story = []

            # Build PDF content
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

            # Process records in batches to manage memory
            for idx, (_, record) in enumerate(folio_data.iterrows(), 1):
                status = record.get('Mapped_Status', 'Unknown')
                active_status = ('Active' if status == 'Live' 
                               else 'Inactive' if status in ['Terminated', 'Expired', 'Pending', 'Cancelled'] 
                               else 'Unknown')
                
                story.append(Paragraph(f"Investment #{idx}", styles['Heading3']))
                story.append(Spacer(1, 8))
                
                color = ('green' if active_status == 'Active' 
                        else 'red' if active_status == 'Inactive' 
                        else 'orange')
                story.append(Paragraph(f"Status: <font color=\"{color}\"><b>{active_status}</b></font>", 
                                     styles['Normal']))
                story.append(Spacer(1, 8))

                # Clean record data and create table
                clean_record = record.dropna()
                table_data = [['Field', 'Value']] + [
                    [str(k), str(v)] for k, v in clean_record.items() 
                    if str(v).strip()
                ]
                
                if len(table_data) > 1:  # Only create table if there's data
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

                # Force garbage collection every 10 records
                if idx % 10 == 0:
                    gc.collect()

            story.append(Paragraph("Generated by Bajaj Capital Folio System", styles['Normal']))
            
            # Build the document
            doc.build(story)
            
            # Clean up story from memory
            del story
            gc.collect()

        # Send file and schedule cleanup
        def remove_file(response):
            try:
                os.unlink(tmp_file.name)
            except:
                pass
            return response

        return send_file(tmp_file.name,
                        mimetype='application/pdf',
                        as_attachment=True,
                        download_name=f'Folio_{folio_number}_Complete_Report.pdf')

    except Exception as e:
        print(f"Error generating PDF: {e}")
        gc.collect()  # Clean up on error
        return render_template('500.html', error_message="Error generating PDF"), 500
    finally:
        # Cleanup
        if 'folio_data' in locals():
            del folio_data
        gc.collect()

@app.errorhandler(400)
def bad_request(error):
    return render_template('400.html'), 400

@app.errorhandler(500)
def internal_error(error):
    gc.collect()  # Clean up on server errors
    return render_template('500.html'), 500

# Clean up cache periodically
@app.before_request
def cleanup_cache():
    """Periodic cache cleanup"""
    global _cached_data, _cache_timestamp
    if (_cache_timestamp and 
        datetime.now().timestamp() - _cache_timestamp > CACHE_DURATION * 2):
        if _cached_data is not None:
            del _cached_data
            _cached_data = None
            _cache_timestamp = None
            gc.collect()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)
