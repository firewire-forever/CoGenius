# PDF-RE: PDF Recognition & Extraction Service
# PDF解析服务 - 使用GPU加速的远程解析服务

from flask import Flask, request, jsonify
from werkzeug.utils import secure_filename
import os
import tempfile
import logging
from datetime import datetime

from pdf_parser import parse_pdf

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configuration
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB max file size
app.config['ALLOWED_EXTENSIONS'] = {'pdf'}
app.config['UPLOAD_FOLDER'] = tempfile.gettempdir()


def allowed_file(filename: str) -> bool:
    """Check if file extension is allowed."""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({
        'status': 'healthy',
        'service': 'PDF-RE',
        'timestamp': datetime.now().isoformat()
    })


@app.route('/parse', methods=['POST'])
def parse_pdf_endpoint():
    """
    Parse a PDF file and return extracted markdown content.

    Request:
        - Method: POST
        - Content-Type: multipart/form-data
        - Parameters:
            - file: PDF file (required)
            - use_ocr: whether to use OCR (optional, default: true)
            - timeout: timeout in seconds (optional, default: 600)

    Response:
        - success: bool
        - markdown: str (extracted content)
        - error: str (error message if failed)
        - page_count: int (number of pages)
        - processing_time: float (seconds)
    """
    start_time = datetime.now()

    # Check if file is present
    if 'file' not in request.files:
        return jsonify({
            'success': False,
            'error': 'No file provided'
        }), 400

    file = request.files['file']

    # Check if file is selected
    if file.filename == '':
        return jsonify({
            'success': False,
            'error': 'No file selected'
        }), 400

    # Check file extension
    if not allowed_file(file.filename):
        return jsonify({
            'success': False,
            'error': 'Only PDF files are allowed'
        }), 400

    # Get optional parameters
    use_ocr = request.form.get('use_ocr', 'true').lower() == 'true'
    timeout = int(request.form.get('timeout', 600))

    # Save uploaded file to temp directory
    filename = secure_filename(file.filename)
    temp_path = os.path.join(app.config['UPLOAD_FOLDER'], f'pdf_re_{datetime.now().strftime("%Y%m%d_%H%M%S")}_{filename}')

    try:
        file.save(temp_path)
        logger.info(f"Saved uploaded file to: {temp_path}")

        # Parse PDF
        logger.info(f"Starting PDF parsing: use_ocr={use_ocr}, timeout={timeout}s")
        result = parse_pdf(temp_path, use_ocr=use_ocr, timeout=timeout)

        processing_time = (datetime.now() - start_time).total_seconds()

        if result['success']:
            logger.info(f"PDF parsing completed in {processing_time:.2f}s, pages: {result.get('page_count', 'unknown')}")
            return jsonify({
                'success': True,
                'markdown': result['markdown'],
                'page_count': result.get('page_count', 0),
                'processing_time': processing_time
            })
        else:
            logger.error(f"PDF parsing failed: {result.get('error', 'Unknown error')}")
            return jsonify({
                'success': False,
                'error': result.get('error', 'Unknown error'),
                'processing_time': processing_time
            }), 500

    except Exception as e:
        logger.exception(f"Error processing PDF: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

    finally:
        # Clean up temp file
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
                logger.debug(f"Cleaned up temp file: {temp_path}")
            except Exception as e:
                logger.warning(f"Failed to clean up temp file: {e}")


@app.route('/parse/base64', methods=['POST'])
def parse_pdf_base64_endpoint():
    """
    Parse a PDF file from base64 encoded content.

    Request:
        - Method: POST
        - Content-Type: application/json
        - Body: {
            "content": "base64 encoded PDF content",
            "use_ocr": true,
            "timeout": 600
        }

    Response:
        - success: bool
        - markdown: str
        - error: str
        - page_count: int
        - processing_time: float
    """
    import base64

    start_time = datetime.now()

    # Get JSON data
    data = request.get_json()

    if not data or 'content' not in data:
        return jsonify({
            'success': False,
            'error': 'No content provided'
        }), 400

    try:
        # Decode base64 content
        pdf_content = base64.b64decode(data['content'])

        # Save to temp file
        temp_path = os.path.join(
            app.config['UPLOAD_FOLDER'],
            f'pdf_re_base64_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf'
        )

        with open(temp_path, 'wb') as f:
            f.write(pdf_content)

        logger.info(f"Saved base64 decoded PDF to: {temp_path}")

        # Get parameters
        use_ocr = data.get('use_ocr', True)
        timeout = data.get('timeout', 600)

        # Parse PDF
        result = parse_pdf(temp_path, use_ocr=use_ocr, timeout=timeout)

        processing_time = (datetime.now() - start_time).total_seconds()

        if result['success']:
            return jsonify({
                'success': True,
                'markdown': result['markdown'],
                'page_count': result.get('page_count', 0),
                'processing_time': processing_time
            })
        else:
            return jsonify({
                'success': False,
                'error': result.get('error', 'Unknown error'),
                'processing_time': processing_time
            }), 500

    except Exception as e:
        logger.exception(f"Error processing base64 PDF: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

    finally:
        # Clean up
        if 'temp_path' in dir() and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except:
                pass


if __name__ == '__main__':
    # Run development server
    # For production, use gunicorn: gunicorn -w 4 -b 0.0.0.0:8000 app:app
    app.run(host='0.0.0.0', port=8000, debug=True)