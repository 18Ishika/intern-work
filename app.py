
# from flask import Flask, request, render_template, send_file
# import os
# import pandas as pd
# import io
# import requests
# from datetime import datetime
# from reportlab.lib.pagesizes import A4
# from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
# from reportlab.lib.styles import getSampleStyleSheet
# from reportlab.lib import colors

# app = Flask(__name__)

# # Google Drive file ID - set this as environment variable
# GOOGLE_DRIVE_FILE_ID = os.getenv('GOOGLE_DRIVE_FILE_ID', '1K9yrMY-qJI5IjAQjrfZ_Odzos0cX0bt1')

# df = None

# def download_csv_from_drive(file_id):
#     """Download CSV from Google Drive using file ID"""
#     try:
#         download_url = f"https://drive.google.com/uc?id={file_id}"
#         print(f"Downloading from: {download_url}")
        
#         response = requests.get(download_url, timeout=30)
#         response.raise_for_status()
        
#         # Read CSV from response content
#         csv_data = pd.read_csv(io.StringIO(response.text))
#         print(f"Successfully downloaded {len(csv_data)} records from Google Drive")
#         return csv_data
        
#     except requests.exceptions.RequestException as e:
#         print(f"Error downloading from Google Drive: {e}")
#         return None
#     except pd.errors.EmptyDataError:
#         print("Error: Downloaded file is empty or not a valid CSV")
#         return None
#     except Exception as e:
#         print(f"Error processing CSV: {e}")
#         return None

# def preprocess_data(df_input):
#     """Preprocess the downloaded data"""
#     df_processed = df_input.copy()
    
#     print(f"Original data: {len(df_processed)} records")
    
#     # Remove duplicates first
#     df_processed = df_processed.drop_duplicates().reset_index(drop=True)
#     print(f"After removing exact duplicates: {len(df_processed)} records")
    
#     # Remove duplicates based on key columns if they exist
#     key_columns = []
#     for col in ['Folio', 'Start Date', 'End Date', 'Amount', 'Scheme Name']:
#         if col in df_processed.columns:
#             key_columns.append(col)
    
#     if key_columns:
#         before_count = len(df_processed)
#         df_processed = df_processed.drop_duplicates(subset=key_columns, keep='first').reset_index(drop=True)
#         print(f"After removing duplicates based on {key_columns}: {len(df_processed)} records")
#         print(f"Removed {before_count - len(df_processed)} duplicate records")
    
#     # Status mapping
#     if 'Status' in df_processed.columns:
#         df_processed['Status'] = df_processed['Status'].astype(str).str.strip().str.lower()
        
#         def map_status(status):
#             if 'live' in status:
#                 return 'Live'
#             elif 'terminated' in status or 'terminatied' in status:
#                 return 'Terminated'
#             elif 'expired' in status:
#                 return 'Expired'
#             elif 'cancelled' in status or 'rejection' in status or 'rejected' in status or 'incorrect' in status or 'failure' in status:
#                 return 'Cancelled'
#             elif 'pause' in status or 'pending' in status or 'marked' in status or 'registration' in status or 'active' in status:
#                 return 'Pending' 
#             else:
#                 return 'Unknown'
        
#         df_processed['Mapped_Status'] = df_processed['Status'].apply(map_status)
    
#     # Frequency formatting
#     if 'Frequency' in df_processed.columns:
#         df_processed['Frequency'] = df_processed['Frequency'].astype(str).str.title()
    
#     return df_processed

# def load_data():
#     """Load data from Google Drive"""
#     global df
    
#     print("Loading data from Google Drive...")
#     csv_data = download_csv_from_drive(GOOGLE_DRIVE_FILE_ID)
    
#     if csv_data is not None:
#         df = preprocess_data(csv_data)
#         print(f'Successfully loaded and processed {len(df)} records')
        
#         if 'Folio' in df.columns:
#             folio_counts = df['Folio'].value_counts()
#             print(f"Unique folios: {len(folio_counts)}")
#             print(f"Folios with multiple investments: {sum(folio_counts > 1)}")
        
#         return True
#     else:
#         print("Failed to load data from Google Drive")
#         return False

# # Error handlers
# @app.errorhandler(400)
# def bad_request(error):
#     return render_template('400.html'), 400

# @app.errorhandler(500)
# def internal_error(error):
#     return render_template('500.html'), 500

# @app.route('/', methods=['GET', 'POST'])
# def index():
#     global df
    
#     # Try to reload data if not available
#     if df is None:
#         print("Data not loaded, attempting to load from Google Drive...")
#         if not load_data():
#             # Return 500 error if data can't be loaded
#             return render_template('500.html', 
#                                  error_message="Unable to load data from Google Drive. Please try again later."), 500
    
#     result = None
#     folio_number = ''
#     error = None
    
#     if request.method == 'POST':
#         folio_number = request.form.get('folio_number', '').strip()
#         print(f"Received folio number: {folio_number}")

#         if not folio_number:
#             error = "Please enter a folio number"
#         else:
#             # Search for folio
#             folio_data = df[df['Folio'].astype(str).str.strip() == folio_number]
#             if not folio_data.empty:
#                 # Process all records for this folio
#                 all_records = []
#                 overall_status = 'Unknown'
#                 active_count = 0
                
#                 for idx, record in folio_data.iterrows():
#                     status = record.get('Mapped_Status', 'Unknown')
#                     if status in ['Live']:
#                         active_status = 'Active'
#                         active_count += 1
#                     elif status in ['Terminated', 'Expired', 'Pending', 'Cancelled']:
#                         active_status = 'Inactive'
#                     else:
#                         active_status = 'Unknown'
                    
#                     all_records.append({
#                         'status': active_status,
#                         'details': record.to_dict()
#                     })
                
#                 # Determine overall status
#                 if active_count > 0:
#                     overall_status = 'Active'
#                 elif active_count == 0 and len(all_records) > 0:
#                     overall_status = 'Inactive'
                
#                 result = {
#                     'folio_number': folio_number,
#                     'status': overall_status, 
#                     'total_investments': len(all_records),
#                     'active_investments': active_count,
#                     'investments': all_records,
#                     'details': all_records[0]['details'] if all_records else {} 
#                 }
#             else:
#                 error = f"Folio number '{folio_number}' not found"
    
#     return render_template('index.html', 
#                          result=result, 
#                          error=error, 
#                          total_records=len(df) if df is not None else 0,
#                          folio_number=folio_number)

# @app.route('/download-folio-report/<folio_number>')
# def download_folio_report(folio_number):
#     global df
    
#     if df is None:
#         if not load_data():
#             return render_template('500.html', 
#                                  error_message="Data not available"), 503
    
#     folio_data = df[df['Folio'].astype(str).str.strip() == folio_number]
    
#     if folio_data.empty:
#         return render_template('400.html', 
#                              error_message="Folio not found"), 404
    
#     try:
#         buffer = io.BytesIO()
#         doc = SimpleDocTemplate(buffer, pagesize=A4)
#         styles = getSampleStyleSheet()
#         story = []
        
#         # Title
#         story.append(Paragraph("Comprehensive Folio Status Report", styles['Title']))
#         story.append(Spacer(1, 20))
        
#         # Company header
#         story.append(Paragraph("Bajaj Capital", styles['Heading2']))
#         story.append(Spacer(1, 12))
        
#         # Report info
#         report_info = f"""
#         Report Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}<br/>
#         Folio Number: {folio_number}<br/>
#         Total Investments: {len(folio_data)}
#         """
#         story.append(Paragraph(report_info, styles['Normal']))
#         story.append(Spacer(1, 20))
        
#         # Investment details
#         for idx, (_, record) in enumerate(folio_data.iterrows(), 1):
#             status = record.get('Mapped_Status', 'Unknown')
#             if status in ['Live']:
#                 active_status = 'Active'
#             elif status in ['Terminated', 'Expired', 'Pending', 'Cancelled']:
#                 active_status = 'Inactive'
#             else:
#                 active_status = 'Unknown'
            
#             # Investment header
#             story.append(Paragraph(f"Investment #{idx}", styles['Heading3']))
#             story.append(Spacer(1, 8))
            
#             # Status with color
#             status_info = f"Status: <font color=\"{'green' if active_status == 'Active' else 'red' if active_status == 'Inactive' else 'orange'}\"><b>{active_status}</b></font>"
#             story.append(Paragraph(status_info, styles['Normal']))
#             story.append(Spacer(1, 8))
            
#             # Details table
#             table_data = [['Field', 'Value']]
#             for key, value in record.items():
#                 if pd.notna(value) and str(value).strip() != '':
#                     table_data.append([str(key), str(value)])
            
#             # Create and style table
#             table = Table(table_data)
#             table.setStyle(TableStyle([
#                 ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
#                 ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
#                 ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
#                 ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
#                 ('FONTSIZE', (0, 0), (-1, 0), 10),
#                 ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
#                 ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
#                 ('GRID', (0, 0), (-1, -1), 1, colors.black),
#                 ('FONTSIZE', (0, 1), (-1, -1), 8),
#             ]))
            
#             story.append(table)
#             story.append(Spacer(1, 15))
        
#         # Footer
#         story.append(Paragraph("Generated by Bajaj Capital Folio System", styles['Normal']))
        
#         # Build PDF
#         doc.build(story)
#         buffer.seek(0)
        
#         return send_file(
#             buffer,
#             mimetype='application/pdf',
#             as_attachment=True,
#             download_name=f'Folio_{folio_number}_Complete_Report.pdf'
#         )
    
#     except Exception as e:
#         print(f"Error generating PDF: {e}")
#         return render_template('500.html', 
#                              error_message="Error generating PDF report"), 500



# if __name__ == '__main__':
#     print("Starting Folio Status Checker...")
#     print(f"Google Drive File ID: {GOOGLE_DRIVE_FILE_ID}")
    
#     # Don't load data on startup - load it on first request instead
#     print("App will load data on first request to avoid startup delays")
    
#     # Get port from environment variable (Render sets this)
#     port = int(os.environ.get('PORT', 5000))
#     print(f"Starting on port: {port}")
#     app.run(debug=False, host='0.0.0.0', port=port)


from flask import Flask, request, render_template, send_file
import os
import sys

print("=== TESTING IMPORTS ===")

try:
    import pandas as pd
    print("✅ pandas imported successfully")
except ImportError as e:
    print(f"❌ pandas import failed: {e}")

try:
    import io
    print("✅ io imported successfully")
except ImportError as e:
    print(f"❌ io import failed: {e}")

try:
    import requests
    print("✅ requests imported successfully")
except ImportError as e:
    print(f"❌ requests import failed: {e}")

try:
    from datetime import datetime
    print("✅ datetime imported successfully")
except ImportError as e:
    print(f"❌ datetime import failed: {e}")

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib import colors
    print("✅ reportlab imported successfully")
except ImportError as e:
    print(f"❌ reportlab import failed: {e}")

print("=== ALL IMPORTS TESTED ===")

app = Flask(__name__)

@app.route('/')
def hello():
    return '<h1>🎉 All Imports Working!</h1><p>Ready for next step!</p>'

@app.route('/health')
def health():
    return {
        'status': 'healthy',
        'port': os.environ.get('PORT', 5000),
        'imports': 'all_successful'
    }

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"=== STARTING SERVER ON PORT {port} ===")
    app.run(debug=False, host='0.0.0.0', port=port)
