"""Offline tests for Alt+L in desktop PDF viewers (organiser/pdfclip.py): python -m unittest tests.test_pdfclip

A fake viewer screenshot (grey background, a PDF page rendered at an odd zoom and scrolled) is cropped like a user
box; locate() must find the right page and rectangle, and rich() must rebuild the text with its formatting.
"""
import tempfile
import unittest
from pathlib import Path

import fitz
from PIL import Image

from organiser import pdfclip


def make_pdf(path):
    doc = fitz.open()
    p1 = doc.new_page(width=595, height=842)
    p1.insert_text((60, 80), "Week 1: Introduction", fontsize=20, fontname="hebo", color=(0.2, 0.35, 0.7))
    for i, y in enumerate(range(120, 400, 16)):
        p1.insert_text((60, y), f"Line {i} of the first page, ordinary body text.", fontsize=11, fontname="helv")
    p2 = doc.new_page(width=595, height=842)
    p2.insert_text((60, 80), "Lecture 3: Block ciphers", fontsize=18, fontname="hebo", color=(0.2, 0.35, 0.7))
    p2.insert_text((60, 110), "The table below compares the ciphers:", fontsize=11, fontname="helv")
    rows = [("Cipher", "Block size", "Key size"), ("DES", "64 bits", "56 bits"), ("AES", "128 bits", "128/192/256 bits")]
    cols, y = [60, 200, 340, 520], 140
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            p2.insert_text((cols[c] + 6, y + 15), cell, fontsize=11, fontname="hebo" if r == 0 else "helv")
        p2.draw_line((cols[0], y), (cols[-1], y), width=0.8)
        y += 22
    p2.draw_line((cols[0], y), (cols[-1], y), width=0.8)
    for cx in cols:
        p2.draw_line((cx, 140), (cx, y), width=0.8)
    p2.insert_text((96, y + 40), "An indented definition line.", fontsize=11, fontname="helv")
    p2.insert_text((230, y + 75), "Centred remark", fontsize=12, fontname="heit")
    doc.save(path)


def viewer_shot(pdf, pno, zoom, left=300, top=-120):
    """Grey 1920x1080 'viewer' with the page drawn at `zoom` px/pt, scrolled so its top is cut off."""
    page = fitz.open(pdf)[pno]
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    shot = Image.new("RGB", (1920, 1080), (82, 86, 89))
    shot.paste(img, (left, top))
    return shot


class LocateAndRebuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.pdf = cls.tmp / "Lecture 03 - Block ciphers.pdf"
        make_pdf(cls.pdf)

    def check(self, pno, zoom, rect_pt, left=300, top=-120):
        shot = viewer_shot(self.pdf, pno, zoom, left, top)
        box = (left + rect_pt[0] * zoom, top + rect_pt[1] * zoom, left + rect_pt[2] * zoom, top + rect_pt[3] * zoom)
        m = pdfclip.locate(self.pdf, shot, box)
        self.assertIsNotNone(m, "box not located")
        self.assertEqual(m.page, pno)
        self.assertAlmostEqual(m.zoom, zoom, delta=zoom * 0.01)
        for got, want in zip(m.rect, rect_pt):
            self.assertAlmostEqual(got, want, delta=2.0)
        return m

    def test_table_page_at_odd_zoom(self):
        m = self.check(1, 1.63, (50, 60, 560, 320), top=-50)       # page top scrolled off, box fully on screen
        html, text = pdfclip.rich(fitz.open(self.pdf)[1], m.rect)
        self.assertIn('<table border="1"', html)
        self.assertIn("128/192/256 bits", html)
        self.assertIn("color:#3359b3", html.lower())        # heading colour from the PDF
        self.assertIn("font-weight:bold", html)
        self.assertIn("margin:0 0pt 0 36pt", html)          # indented line keeps its indent
        self.assertIn("margin:0 0pt 0 170pt", html)         # the remark keeps its position
        self.assertIn("Cipher\tBlock size\tKey size", text)

    def test_first_page_small_zoom(self):
        m = self.check(0, 0.93, (50, 100, 400, 300), left=500, top=40)
        _, text = pdfclip.rich(fitz.open(self.pdf)[0], m.rect)
        self.assertIn("Line 3 of the first page", text)

    def test_blank_box_is_not_guessed(self):
        shot = viewer_shot(self.pdf, 0, 1.2)
        self.assertIsNone(pdfclip.locate(self.pdf, shot, (10, 10, 200, 200)))   # grey background only

    def test_title_to_name(self):
        self.assertEqual(pdfclip.pdf_name_from_title("Lecture 01 - Academic Debate.pdf - Adobe Acrobat Reader (64-bit)"),
                         "Lecture 01 - Academic Debate.pdf")
        self.assertIsNone(pdfclip.pdf_name_from_title("Adobe Acrobat Reader"))


if __name__ == "__main__":
    unittest.main()
