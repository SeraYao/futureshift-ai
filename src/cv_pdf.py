"""In-memory selectable-text PDF extraction with sanitized errors and bounded input."""
from io import BytesIO
import logging
import threading
import warnings
from typing import Callable

MAX_PDF_BYTES = 3 * 1024 * 1024
MAX_PAGES = 5
MAX_EXTRACTED_CHARS = 50_000


class CVError(ValueError):
    """A safe user-facing error that never contains document text or credentials."""


class _QuietParser(logging.Filter):
    """Suppress parser diagnostics for this document/thread rather than logging CV fragments."""

    def __init__(self) -> None:
        """Remember only the parsing thread, without recording any document data."""
        super().__init__()
        self.thread_id = threading.get_ident()

    def filter(self, record: logging.LogRecord) -> bool:
        """Allow only records originating outside the current parsing thread."""
        return record.thread != self.thread_id


def extract_pdf(filename: str, content: bytes, reader_factory: Callable | None = None) -> str:
    """Validate PDF suffix/signature/size/pages and extract text without disk writes or OCR."""
    if not isinstance(filename, str) or not filename.lower().endswith('.pdf'):
        raise CVError('Only .pdf files are accepted. Please use the questionnaire for other formats.')
    if not isinstance(content, bytes) or not content or len(content) > MAX_PDF_BYTES:
        raise CVError('PDF must be nonempty and at most 3 MB.')
    if not content.startswith(b'%PDF-'):
        raise CVError('The file does not have a valid PDF signature.')
    if reader_factory is None:
        try:
            from pypdf import PdfReader
        except ImportError:
            raise CVError('PDF support is unavailable. Install the project requirements or fill in the questionnaire.') from None
        reader_factory = PdfReader
    loggers = [logging.getLogger('pypdf')] + [value for key, value in logging.Logger.manager.loggerDict.items()
                                             if key.startswith('pypdf.') and isinstance(value, logging.Logger)]
    quiet = _QuietParser()
    for logger in loggers:
        logger.addFilter(quiet)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            reader = reader_factory(BytesIO(content), strict=True)
            if reader.is_encrypted:
                raise CVError('Encrypted PDFs are not supported. Use an unencrypted text PDF or the questionnaire.')
            if not 1 <= len(reader.pages) <= MAX_PAGES:
                raise CVError('Upload a PDF with 1–5 pages, or use the questionnaire.')
            parts, total = [], 0
            for page in reader.pages:
                text = page.extract_text() or ''
                remaining = MAX_EXTRACTED_CHARS - total
                parts.append(text[:remaining])
                total += len(parts[-1])
                if total >= MAX_EXTRACTED_CHARS:
                    break
            result = '\n'.join(parts).strip()
            if not result or not any(character.isalnum() for character in result):
                raise CVError('No selectable text found. Scanned/image PDFs need OCR, which is not supported. Fill in the questionnaire.')
            return result
    except CVError:
        raise
    except Exception:
        raise CVError('This PDF is damaged or cannot be parsed. Please fill in the questionnaire.') from None
    finally:
        for logger in loggers:
            logger.removeFilter(quiet)
