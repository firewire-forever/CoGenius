# PDF Parser Module
# Supports multiple parsing backends with GPU acceleration

import os
import logging
import tempfile
import threading
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


def parse_with_marker(pdf_path: str, timeout: int = 600) -> Dict[str, Any]:
    """
    Parse PDF using marker (high quality, GPU accelerated).

    Args:
        pdf_path: Path to PDF file
        timeout: Timeout in seconds

    Returns:
        Dict with success, markdown, page_count, error
    """
    try:
        from marker.converters.pdf import PdfConverter
        from marker.models import create_model_dict
        from marker.output import text_from_rendered

        logger.info(f"[MARKER] Starting high-quality PDF parsing...")

        # Create converter with GPU support
        converter = PdfConverter(
            artifact_dict=create_model_dict(),
        )

        # Parse PDF
        rendered = converter(pdf_path)
        markdown, _, _ = text_from_rendered(rendered)

        # Get page count
        page_count = len(rendered.pages) if hasattr(rendered, 'pages') else 0

        logger.info(f"[MARKER] Successfully parsed PDF, {len(markdown)} chars, {page_count} pages")

        return {
            'success': True,
            'markdown': markdown,
            'page_count': page_count,
            'error': None
        }

    except ImportError as e:
        logger.warning(f"[MARKER] marker not installed: {e}")
        return {
            'success': False,
            'markdown': '',
            'page_count': 0,
            'error': f'marker library not installed: {e}'
        }
    except Exception as e:
        logger.exception(f"[MARKER] Error parsing PDF: {e}")
        return {
            'success': False,
            'markdown': '',
            'page_count': 0,
            'error': str(e)
        }


def parse_with_pdfplumber(pdf_path: str) -> Dict[str, Any]:
    """
    Parse PDF using pdfplumber (fast, no GPU needed).

    Args:
        pdf_path: Path to PDF file

    Returns:
        Dict with success, markdown, page_count, error
    """
    try:
        import pdfplumber

        logger.info(f"[PDFPLUMBER] Starting fast PDF parsing...")

        text_parts = []
        page_count = 0

        with pdfplumber.open(pdf_path) as pdf:
            page_count = len(pdf.pages)
            for i, page in enumerate(pdf.pages):
                page_text = page.extract_text() or ""
                text_parts.append(f"--- Page {i+1} ---\n{page_text}")

        markdown = "\n\n".join(text_parts)

        logger.info(f"[PDFPLUMBER] Successfully parsed PDF, {len(markdown)} chars, {page_count} pages")

        return {
            'success': True,
            'markdown': markdown,
            'page_count': page_count,
            'error': None
        }

    except ImportError as e:
        logger.warning(f"[PDFPLUMBER] pdfplumber not installed: {e}")
        return {
            'success': False,
            'markdown': '',
            'page_count': 0,
            'error': f'pdfplumber library not installed: {e}'
        }
    except Exception as e:
        logger.exception(f"[PDFPLUMBER] Error parsing PDF: {e}")
        return {
            'success': False,
            'markdown': '',
            'page_count': 0,
            'error': str(e)
        }


def parse_with_pypdf(pdf_path: str) -> Dict[str, Any]:
    """
    Parse PDF using pypdf (fastest, basic extraction).

    Args:
        pdf_path: Path to PDF file

    Returns:
        Dict with success, markdown, page_count, error
    """
    try:
        from pypdf import PdfReader

        logger.info(f"[PYPDF] Starting basic PDF parsing...")

        reader = PdfReader(pdf_path)
        page_count = len(reader.pages)

        text_parts = []
        for i, page in enumerate(reader.pages):
            page_text = page.extract_text() or ""
            text_parts.append(f"--- Page {i+1} ---\n{page_text}")

        markdown = "\n\n".join(text_parts)

        logger.info(f"[PYPDF] Successfully parsed PDF, {len(markdown)} chars, {page_count} pages")

        return {
            'success': True,
            'markdown': markdown,
            'page_count': page_count,
            'error': None
        }

    except ImportError as e:
        logger.warning(f"[PYPDF] pypdf not installed: {e}")
        return {
            'success': False,
            'markdown': '',
            'page_count': 0,
            'error': f'pypdf library not installed: {e}'
        }
    except Exception as e:
        logger.exception(f"[PYPDF] Error parsing PDF: {e}")
        return {
            'success': False,
            'markdown': '',
            'page_count': 0,
            'error': str(e)
        }


def parse_pdf(
    pdf_path: str,
    use_ocr: bool = True,
    timeout: int = 600,
    prefer_backend: str = 'auto'
) -> Dict[str, Any]:
    """
    Parse a PDF file using the best available backend.

    Args:
        pdf_path: Path to PDF file
        use_ocr: Whether to use OCR (high quality) mode
        timeout: Timeout in seconds for OCR mode
        prefer_backend: Preferred backend ('marker', 'pdfplumber', 'pypdf', 'auto')

    Returns:
        Dict with:
            - success: bool
            - markdown: str (extracted content)
            - page_count: int
            - error: str (error message if failed)
    """
    logger.info(f"[PDF_PARSER] Parsing: {pdf_path}")
    logger.info(f"[PDF_PARSER] Options: use_ocr={use_ocr}, timeout={timeout}s, prefer_backend={prefer_backend}")

    # Determine which backend to use
    if prefer_backend == 'auto':
        if use_ocr:
            # Try marker first (high quality), fall back to pdfplumber
            backends = ['marker', 'pdfplumber', 'pypdf']
        else:
            # Fast mode: skip marker
            backends = ['pdfplumber', 'pypdf']
    elif prefer_backend in ['marker', 'pdfplumber', 'pypdf']:
        backends = [prefer_backend]
    else:
        backends = ['pdfplumber', 'pypdf']

    # Try each backend in order
    last_error = None

    for backend in backends:
        logger.info(f"[PDF_PARSER] Trying backend: {backend}")

        try:
            if backend == 'marker':
                if not use_ocr:
                    logger.info("[PDF_PARSER] Skipping marker (use_ocr=False)")
                    continue
                result = parse_with_marker(pdf_path, timeout=timeout)
            elif backend == 'pdfplumber':
                result = parse_with_pdfplumber(pdf_path)
            elif backend == 'pypdf':
                result = parse_with_pypdf(pdf_path)
            else:
                continue

            if result['success']:
                logger.info(f"[PDF_PARSER] Successfully parsed with {backend}")
                return result
            else:
                last_error = result.get('error', 'Unknown error')
                logger.warning(f"[PDF_PARSER] Backend {backend} failed: {last_error}")

        except Exception as e:
            last_error = str(e)
            logger.warning(f"[PDF_PARSER] Backend {backend} raised exception: {e}")

    # All backends failed
    logger.error(f"[PDF_PARSER] All backends failed. Last error: {last_error}")
    return {
        'success': False,
        'markdown': '',
        'page_count': 0,
        'error': f'All backends failed. Last error: {last_error}'
    }


# Convenience function for direct imports
def pdf_to_markdown(pdf_path: str, use_ocr: bool = True, timeout: int = 600) -> str:
    """
    Simple function to convert PDF to markdown.

    Args:
        pdf_path: Path to PDF file
        use_ocr: Whether to use OCR mode
        timeout: Timeout in seconds

    Returns:
        Markdown text

    Raises:
        RuntimeError: If parsing fails
    """
    result = parse_pdf(pdf_path, use_ocr=use_ocr, timeout=timeout)

    if result['success']:
        return result['markdown']
    else:
        raise RuntimeError(f"PDF parsing failed: {result['error']}")


if __name__ == '__main__':
    # Test mode
    import sys

    if len(sys.argv) < 2:
        print("Usage: python pdf_parser.py <pdf_path> [--fast]")
        sys.exit(1)

    pdf_path = sys.argv[1]
    use_ocr = '--fast' not in sys.argv

    print(f"Parsing PDF: {pdf_path}")
    print(f"OCR mode: {use_ocr}")

    result = parse_pdf(pdf_path, use_ocr=use_ocr)

    if result['success']:
        print(f"\n✅ Success!")
        print(f"Pages: {result['page_count']}")
        print(f"Characters: {len(result['markdown'])}")
        print("\n--- Preview (first 500 chars) ---")
        print(result['markdown'][:500])
    else:
        print(f"\n❌ Failed: {result['error']}")