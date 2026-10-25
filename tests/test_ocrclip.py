"""Offline test for Alt+L in any desktop app (organiser/ocrclip.py, Windows OCR): python -m unittest tests.test_ocrclip"""
import tempfile
import unittest
from pathlib import Path

import fitz
from PIL import Image

from organiser import ocrclip
from tests.test_pdfclip import make_pdf


class ScreenText(unittest.TestCase):
    def test_table_and_paragraphs_from_pixels(self):
        pdf = Path(tempfile.mkdtemp()) / "t.pdf"
        make_pdf(pdf)
        pix = fitz.open(pdf)[1].get_pixmap(matrix=fitz.Matrix(1.6, 1.6), alpha=False)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).crop((60, 80, 900, 560))
        html, text = ocrclip.screen_rich(img, 1.0)
        self.assertIn('<table border="1"', html)
        self.assertIn("Cipher\tBlock size\tKey size", text)
        self.assertIn("128/192/256 bits", text)
        self.assertIn("The table below compares the ciphers:", text)

    def test_dark_chat_reads_exactly(self):
        """Small light text on a dark chat background (like Claude / ChatGPT dark mode)."""
        from PIL import ImageDraw, ImageFont
        lines = ["it's a PDF viewer inside the page, so it now goes through the same layout engine as",
                 "the built-in reader: real paragraphs, tables from their grid lines.", "",
                 "All 22 extension checks and 20 offline checks pass. Overleaf, Gemini, Acrobat and",
                 "the other apps haven't been tried on your real screen, so please tell me."]
        font = ImageFont.truetype(r"C:\Windows\Fonts\segoeui.ttf", 15)
        img = Image.new("RGB", (700, 130), (38, 38, 36))
        d = ImageDraw.Draw(img)
        for k, l in enumerate(lines):
            d.text((10, 8 + 22 * k), l, font=font, fill=(229, 229, 226))
        html, text = ocrclip.screen_rich(img, 1.0)
        self.assertEqual(text.split("\n"), [lines[0] + " " + lines[1], lines[3] + " " + lines[4]])
        self.assertNotIn("<table", html)
        self.assertIn("color:#000000", html)

    def test_dark_theme_text_becomes_dark(self):
        self.assertEqual(ocrclip.readable((235, 235, 235), (20, 20, 25)), "#000000")
        self.assertEqual(ocrclip.readable((20, 20, 20), (255, 255, 255)), "#000000")


if __name__ == "__main__":
    unittest.main()
