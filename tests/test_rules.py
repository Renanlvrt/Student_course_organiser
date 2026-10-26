"""Offline tests (no AI): python -m unittest discover -s tests"""
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from organiser import placer, rules
from organiser.classify import classify
from organiser.config import load_config


def cfg_in(tmp):
    cfg = load_config()
    cfg.root_folder = Path(tmp) / "courses"
    cfg.downloads_folder = Path(tmp) / "Downloads"
    return cfg


class Rules(unittest.TestCase):
    def test_category(self):
        cases = {
            "Answers to Practice Questions of Lecture 1": "Solutions",
            "Slides for Probability Lecture 10": "Lectures",
            "dl-practical1": "Practicals",
            "week12(1) (1)": "Lectures",
            "Coursework 1 specification": "Assessment",
            "past paper 2024": "Exam Prep",
            "questions (2)": "Practicals",
        }
        for s, want in cases.items():
            self.assertEqual(rules.category_from_text(rules.clean_stem(s + ".pdf")), (want, rules.category_from_text(rules.clean_stem(s + ".pdf"))[1]), s)

    def test_number(self):
        self.assertEqual(rules.number_from_text("dl-lecture1"), 1)
        self.assertEqual(rules.number_from_text("Answer to Practice Question of Lecture 7"), 7)
        self.assertEqual(rules.number_from_text("week12(1) (1)"), 12)
        self.assertEqual(rules.number_from_text("L03 slides"), 3)
        self.assertIsNone(rules.number_from_text("notes (2)"))

    def test_topic(self):
        self.assertEqual(rules.clean_topic("Lecture 3: block ciphers and AES"), "Block Ciphers and AES")
        self.assertEqual(rules.clean_topic("COMP3731 Cryptography (26/27)"), "Cryptography")
        self.assertNotIn(":", rules.clean_topic("RSA: the basics?"))

    def test_real_blackboard_names(self):
        self.assertEqual(rules.number_from_text("AGT 1 - Introduction, games and Nash equilibria - slides"), 1)
        self.assertEqual(rules.number_from_text("2 Nash's Theorem"), 2)
        self.assertEqual(rules.number_from_text("weeks3-4-questions-potential"), 3)
        self.assertEqual(rules.clean_topic("AGT 1 - Introduction, games and Nash equilibria - slides (2).pdf"),
                         "Introduction, Games and Nash Equilibria")
        self.assertEqual(rules.clean_topic("week1-questions.pdf"), "Questions")
        self.assertEqual(rules.clean_topic("Week 2 answers 1a and 1b"), "Answers 1a and 1b")
        self.assertEqual(rules.clean_topic(rules.clean_topic("Week 2 answers 1a and 1b")), "Answers 1a and 1b")
        self.assertTrue(rules.is_junk_title("ultraDocumentBody Copy"))
        self.assertEqual(rules.category_from_text("Formative Exercises")[0], "Practicals")
        self.assertTrue(placer._needs_name("Lecture", "Lecture 01 - ultraDocumentBody Copy"))
        self.assertTrue(placer._needs_name("Practical", "Practical 03"))
        self.assertFalse(placer._needs_name("Lecture", "Lecture 01 - Introduction"))

    def test_blackboard_lines(self):
        cfg = load_config()
        base = {"course_code": "COMP3801", "chain": ["Practicals", "Deep Learning"]}
        ans = classify(cfg, "dl-answers1.pdf", "", "", use_ai=False,
                       context={**base, "item_title": "Practical 1: NCC/Colab setup", "link_text": "answers"})
        self.assertEqual((ans.category, ans.number, ans.relates_to), ("Solutions", 1, "Practicals"))
        mock = classify(cfg, "dl-practical10.pdf", "", "", use_ai=False,
                        context={**base, "item_title": "Practical 10: Mock exam and Q&A", "link_text": "pdf"})
        self.assertEqual((mock.category, mock.number), ("Practicals", 10))
        from organiser import notebooks
        self.assertEqual(notebooks.raw_url("https://colab.research.google.com/gist/cwkx/abc123/unet.ipynb"),
                         "https://gist.githubusercontent.com/cwkx/abc123/raw/unet.ipynb")
        self.assertIsNone(notebooks.raw_url("https://colab.research.google.com/drive/1XyZ"))
        self.assertEqual(rules.clean_topic(rules.citation_title(
            "He, K., Zhang, X. (2016). Deep residual learning for image recognition. In CVPR")),
            "Deep Residual Learning for Image Recognition")

    def test_part_label(self):
        cfg = load_config()
        crypto = cfg.module("Crypto")
        self.assertEqual(rules.part_from_label(crypto, "Part 1: Symmetric Cryptography"), 0)
        self.assertEqual(rules.part_from_label(crypto, "Part 2: Asymmetric Cryptography"), 1)
        aads = cfg.module("AADS")
        self.assertEqual(rules.part_from_label(aads, "Part II: Advanced Algorithms"), 1)
        self.assertEqual(rules.part_from_label(aads, "Part I: Design of Algorithms and Data Structures"), 0)

    def test_term(self):
        self.assertEqual(rules.part_by_term(datetime(2026, 10, 21)), 0)
        self.assertEqual(rules.part_by_term(datetime(2027, 2, 1)), 1)


class Classify(unittest.TestCase):
    def test_blackboard_wins(self):
        cfg = load_config()
        ctx = {"course_code": "COMP3731_2026", "course_name": "Cryptography (26/27)",
               "chain": ["Lectures", "Part 2: Asymmetric Cryptography"], "item_title": "Lecture 12 - RSA"}
        c = classify(cfg, "slides.pdf", "", "", context=ctx, manual_module="AADS", use_ai=False)
        self.assertEqual((c.module, c.part, c.category, c.number), ("Crypto", 1, "Lectures", 12))
        self.assertGreaterEqual(c.confidence, 0.7)

    def test_other_course_layouts(self):
        """Terms, weeks and practicals-only sections, however a course nests them (innermost first)."""
        cfg = load_config()
        course = {"course_code": "COMP3731_2026", "course_name": "Cryptography (26/27)"}
        for chain, part in ((["Practical 3", "Practicals", "Term2 [Crypto]"], 1),
                            (["Practical 3", "Week 15", "Epiphany term"], 1),
                            (["Practical 3", "Practicals", "Michaelmas"], 0)):
            c = classify(cfg, "sheet.pdf", "", "", context={**course, "chain": chain, "item_title": "Exercises"},
                         use_ai=False, when=datetime(2026, 10, 1))
            self.assertEqual((c.part, c.category), (part, "Practicals"), chain)

    def test_manual_pick_and_prefix(self):
        cfg = load_config()
        c = classify(cfg, "dl-lecture1.pdf", "Introduction to deep learning neural networks", "Intro", use_ai=False)
        self.assertEqual((c.module, c.part, c.category, c.number), ("DLCV", 0, "Lectures", 1))

    def test_assessment_module_level(self):
        cfg = load_config()
        c = classify(cfg, "Coursework brief.pdf", "", "", manual_module="Crypto", use_ai=False)
        self.assertEqual((c.module, c.part, c.category), ("Crypto", None, "Assessment"))

    def test_unreadable_low_conf(self):
        cfg = load_config()
        c = classify(cfg, "lecture3.pdf", "", "", manual_module="Crypto", error="bad pdf", use_ai=False)
        self.assertLess(c.confidence, cfg.confidence_threshold)


class Placement(unittest.TestCase):
    def test_names_and_bundling(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = cfg_in(tmp)
            ctx = {"course_code": "COMP3801_2026", "course_name": "Deep Learning & Computer Vision",
                   "chain": ["Deep Learning"], "item_title": "Practical 2"}
            code = classify(cfg, "dl-practical2.py", "", "", context=ctx, use_ai=False)
            pl = placer.plan(cfg, code, "dl-practical2.py")
            self.assertEqual(pl.dest.relative_to(cfg.root_folder).as_posix(),
                             "DLCV/Practicals/Deep Learning/Practical 02/dl-practical2.py")
            placer.move(self._touch(tmp, "dl-practical2.py"), pl.dest)
            sheet = classify(cfg, "dl-practical2.pdf", "", "", context=ctx, use_ai=False)
            sheet.topic = "Training CNNs"
            pl2 = placer.plan(cfg, sheet, "dl-practical2.pdf")
            self.assertEqual(pl2.dest.relative_to(cfg.root_folder).as_posix(),
                             "DLCV/Practicals/Deep Learning/Practical 02 - Training CNNs/Practical 02 - Training CNNs.pdf")
            self.assertIsNotNone(pl2.rename_folder)

    def test_lecture_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = cfg_in(tmp)
            c = classify(cfg, "slides.pdf", "", "", manual_module="Crypto", manual_part=0, use_ai=False)
            c.category, c.topic, c.confidence = "Lectures", "Block Ciphers", 1.0
            p1 = placer.plan(cfg, c, "slides.pdf").dest
            self.assertEqual(p1.relative_to(cfg.root_folder / "Crypto/Lectures/Symmetric Cryptography").as_posix(),
                             "Lecture 01 - Block Ciphers/Lecture 01 - Block Ciphers.pdf")
            placer.move(self._touch(tmp, "a.pdf"), p1)
            # unnumbered -> next free folder
            self.assertEqual(placer.plan(cfg, c, "slides.pdf").dest.parent.name, "Lecture 02 - Block Ciphers")
            # same number, other document (notes chapter) -> same folder, own name
            c.number, c.topic = 1, "Notes on AES"
            self.assertEqual(placer.plan(cfg, c, "notes.pdf").dest, p1.parent / "Lecture 01 - Notes on AES.pdf")
            # same number, same name -> (2), never overwrite
            c.topic = "Block Ciphers"
            self.assertEqual(placer.plan(cfg, c, "slides.pdf").dest.name, "Lecture 01 - Block Ciphers (2).pdf")
            # number 10 must not join the 'Lecture 01' folder
            c.number = 10
            self.assertEqual(placer.plan(cfg, c, "x.pdf").dest.parent.name, "Lecture 10 - Block Ciphers")

    def test_attached_and_other(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = cfg_in(tmp)
            rel = lambda p: p.relative_to(cfg.root_folder).as_posix()
            sol = classify(cfg, "Answers to practical 3.pdf", "", "", manual_module="Crypto", manual_part=0, use_ai=False)
            sol.topic = "AES"
            self.assertEqual(rel(placer.plan(cfg, sol, "a.pdf").dest),
                             "Crypto/Practicals/Symmetric Cryptography/Practical 03/Solutions 03 - AES.pdf")
            lsol = classify(cfg, "Answers to Practice Questions of Lecture 6.docx", "", "", manual_module="Crypto",
                            manual_part=0, use_ai=False)
            lsol.topic = "Practice Questions"
            self.assertEqual(rel(placer.plan(cfg, lsol, "b.docx").dest),
                             "Crypto/Lectures/Symmetric Cryptography/Lecture 06/Solutions 06 - Practice Questions.docx")
            paper = classify(cfg, "attention.pdf", "", "", manual_module="DLCV", manual_part=0, use_ai=False,
                             context={"course_code": "COMP3801", "chain": ["Curated Papers", "Deep Learning"]})
            paper.topic = "Attention Is All You Need"
            self.assertEqual(paper.category, "Readings")
            self.assertEqual(rel(placer.plan(cfg, paper, "attention.pdf").dest),
                             "DLCV/Lectures/Deep Learning/Readings/Attention Is All You Need.pdf")
            # link text names extra files on a lecture page; "slides" keeps the lecture topic
            ctx = {"course_code": "COMP3801", "chain": ["Slides and Code", "Deep Learning"],
                   "item_title": "Lecture 10: Generalisation theory", "link_text": "proof"}
            proof = classify(cfg, "proof.pdf", "", "", context=ctx, use_ai=False)
            self.assertEqual((proof.category, proof.number, proof.topic), ("Lectures", 10, "Proof"))
            slides = classify(cfg, "dl-lecture10.pdf", "", "", context={**ctx, "link_text": "slides"}, use_ai=False)
            self.assertEqual((slides.number, slides.topic), (10, "Generalisation Theory"))
            brief = classify(cfg, "Coursework brief.pdf", "", "", manual_module="Crypto", use_ai=False)
            brief.topic = "Coursework Brief"
            self.assertEqual(rel(placer.plan(cfg, brief, "c.pdf").dest), "Crypto/Other/Coursework Brief.pdf")

    @staticmethod
    def _touch(tmp, name):
        p = Path(tmp) / "src" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
        return p


if __name__ == "__main__":
    unittest.main()
