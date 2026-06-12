from unittest.mock import MagicMock, patch

from municipaliq import ocr


class TestSidecarPath:
    def test_sidecar_alongside_pdf(self, tmp_path):
        pdf = tmp_path / 'doc.pdf'
        assert ocr._sidecar_path(pdf) == tmp_path / 'doc_text.txt'

    def test_preserves_directory(self, tmp_path):
        pdf = tmp_path / 'sub' / 'meeting.pdf'
        sidecar = ocr._sidecar_path(pdf)
        assert sidecar.parent == tmp_path / 'sub'


class TestExtractWithPypdf:
    def test_returns_text_from_digital_pdf(self, tmp_path):
        pdf = tmp_path / 'doc.pdf'
        pdf.write_bytes(b'%PDF fake')
        mock_reader = MagicMock()
        mock_reader.pages = [MagicMock()]
        mock_reader.pages[0].extract_text.return_value = 'Meeting Minutes April 2025'
        with patch('municipaliq.ocr.PdfReader', return_value=mock_reader):
            result = ocr._extract_with_pypdf(pdf.read_bytes())
        assert 'Meeting Minutes' in result

    def test_returns_empty_for_scanned_pdf(self, tmp_path):
        pdf = tmp_path / 'scan.pdf'
        pdf.write_bytes(b'%PDF fake')
        mock_reader = MagicMock()
        mock_reader.pages = [MagicMock()]
        mock_reader.pages[0].extract_text.return_value = ''
        with patch('municipaliq.ocr.PdfReader', return_value=mock_reader):
            result = ocr._extract_with_pypdf(pdf.read_bytes())
        assert result == ''

    def test_returns_empty_on_exception(self):
        with patch('municipaliq.ocr.PdfReader', side_effect=Exception('bad pdf')):
            result = ocr._extract_with_pypdf(b'garbage')
        assert result == ''


class TestOcrPages:
    def test_calls_tesseract_on_each_page(self):
        mock_img = MagicMock()
        with patch('municipaliq.ocr.convert_from_bytes', return_value=[mock_img, mock_img]), \
             patch('municipaliq.ocr.pytesseract.image_to_string',
                   return_value='Board Minutes') as mock_ocr:
            result = ocr._ocr_pages(b'fake pdf bytes')
        assert mock_ocr.call_count == 2
        assert 'Board Minutes' in result

    def test_returns_empty_on_exception(self):
        with patch('municipaliq.ocr.convert_from_bytes',
                   side_effect=Exception('poppler error')):
            result = ocr._ocr_pages(b'bad bytes')
        assert result == ''


class TestExtractText:
    def test_returns_cached_text_when_sidecar_exists(self, tmp_path):
        pdf = tmp_path / 'doc.pdf'
        pdf.write_bytes(b'%PDF')
        sidecar = tmp_path / 'doc_text.txt'
        sidecar.write_text('Cached meeting minutes text')
        result = ocr.extract_text(pdf)
        assert result == 'Cached meeting minutes text'

    def test_skips_cache_when_use_cache_false(self, tmp_path):
        pdf = tmp_path / 'doc.pdf'
        pdf.write_bytes(b'%PDF')
        (tmp_path / 'doc_text.txt').write_text('old cached text')
        with patch.object(ocr, '_extract_with_pypdf', return_value='fresh text'), \
             patch.object(ocr, '_ocr_pages', return_value=''):
            result = ocr.extract_text(pdf, use_cache=False)
        assert result == 'fresh text'

    def test_falls_back_to_ocr_when_pypdf_empty(self, tmp_path):
        pdf = tmp_path / 'doc.pdf'
        pdf.write_bytes(b'%PDF')
        with patch.object(ocr, '_extract_with_pypdf', return_value=''), \
             patch.object(ocr, '_ocr_pages', return_value='OCR text from scan'):
            result = ocr.extract_text(pdf)
        assert result == 'OCR text from scan'

    def test_saves_sidecar_after_extraction(self, tmp_path):
        pdf = tmp_path / 'doc.pdf'
        pdf.write_bytes(b'%PDF')
        with patch.object(ocr, '_extract_with_pypdf', return_value='extracted text'), \
             patch.object(ocr, '_ocr_pages', return_value=''):
            ocr.extract_text(pdf)
        assert (tmp_path / 'doc_text.txt').read_text() == 'extracted text'

    def test_does_not_save_sidecar_when_no_text(self, tmp_path):
        pdf = tmp_path / 'doc.pdf'
        pdf.write_bytes(b'%PDF')
        with patch.object(ocr, '_extract_with_pypdf', return_value=''), \
             patch.object(ocr, '_ocr_pages', return_value=''):
            ocr.extract_text(pdf)
        assert not (tmp_path / 'doc_text.txt').exists()

    def test_uses_pypdf_text_without_calling_ocr(self, tmp_path):
        pdf = tmp_path / 'doc.pdf'
        pdf.write_bytes(b'%PDF')
        with patch.object(ocr, '_extract_with_pypdf', return_value='digital text') as mock_pdf, \
             patch.object(ocr, '_ocr_pages') as mock_ocr:
            ocr.extract_text(pdf)
        mock_pdf.assert_called_once()
        mock_ocr.assert_not_called()
