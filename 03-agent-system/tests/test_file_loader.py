"""知识文件提取测试：txt（UTF-8/GBK）、md、csv（FAQ/普通表）、pdf、docx。

pdf 用手工构造的极小 PDF 字节常量（pypdf 只能读不能写文本）；
pdf / docx 用例在对应解析库未安装时跳过，保证离线可跑。
"""
import importlib.util
import io
import unittest

from retrieval.file_loader import extract_text


def _build_pdf(text: str) -> bytes:
    """构造只含一行文本的最小合法 PDF（Helvetica，ASCII 文本）。"""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj ".encode() + body + b" endobj\n"
    xref_pos = len(out)
    out += b"xref\n0 6\n0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += b"trailer << /Size 6 /Root 1 0 R >>\nstartxref\n" + str(xref_pos).encode() + b"\n%%EOF\n"
    return bytes(out)


class TestPlainText(unittest.TestCase):
    def test_txt_utf8(self):
        text = extract_text("智能门锁 S1 售价 899 元".encode("utf-8"), "产品.txt")
        self.assertIn("899", text)

    def test_txt_utf8_with_bom(self):
        data = "智能门锁".encode("utf-8-sig")
        self.assertEqual(extract_text(data, "x.txt"), "智能门锁")

    def test_txt_gbk(self):
        text = extract_text("扫地机器人 R3 支持自动回充".encode("gbk"), "产品.txt")
        self.assertIn("自动回充", text)

    def test_md_passthrough(self):
        text = extract_text("# 售后政策\n\n整机保修一年".encode("utf-8"), "售后.md")
        self.assertIn("整机保修一年", text)


class TestCsv(unittest.TestCase):
    def test_faq_chinese_headers(self):
        csv_data = "问题,回答\n门锁多少钱,899 元\n怎么保修,整机保修一年\n".encode("utf-8")
        text = extract_text(csv_data, "faq.csv")
        self.assertIn("问：门锁多少钱", text)
        self.assertIn("答：899 元", text)

    def test_faq_english_headers(self):
        csv_data = "question,answer\nprice?,899 CNY\n".encode("utf-8")
        text = extract_text(csv_data, "faq.csv")
        self.assertIn("问：price?", text)

    def test_plain_table_rows_joined(self):
        csv_data = "型号,价格\nS1,899\nR3,1999\n".encode("utf-8")
        text = extract_text(csv_data, "products.csv")
        self.assertIn("S1 | 899", text)
        self.assertIn("R3 | 1999", text)


@unittest.skipUnless(importlib.util.find_spec("pypdf"), "pypdf 未安装")
class TestPdf(unittest.TestCase):
    def test_pdf_text_extracted(self):
        text = extract_text(_build_pdf("Hello knowledge base 899"), "manual.pdf")
        self.assertIn("Hello knowledge base 899", text)

    def test_scanned_pdf_empty_text_rejected(self):
        # 构造无文本层的 PDF（Contents 为空流）
        stream = b""
        out = bytearray(b"%PDF-1.4\n")
        out += b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        out += b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
        out += b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >> endobj\n"
        data = bytes(out) + b"trailer << /Size 4 /Root 1 0 R >>\n%%EOF\n"
        with self.assertRaises(ValueError):
            extract_text(data, "scan.pdf")


@unittest.skipUnless(importlib.util.find_spec("docx"), "python-docx 未安装")
class TestDocx(unittest.TestCase):
    def test_docx_paragraphs_and_table(self):
        import docx

        document = docx.Document()
        document.add_paragraph("智能门锁 S1 支持指纹开锁，售价 899 元。")
        table = document.add_table(rows=2, cols=2)
        table.cell(0, 0).text = "型号"
        table.cell(0, 1).text = "S1"
        table.cell(1, 0).text = "价格"
        table.cell(1, 1).text = "899"
        buffer = io.BytesIO()
        document.save(buffer)

        text = extract_text(buffer.getvalue(), "产品.docx")
        self.assertIn("指纹开锁", text)
        self.assertIn("型号 | S1", text)
        self.assertIn("价格 | 899", text)


class TestErrors(unittest.TestCase):
    def test_unknown_suffix(self):
        with self.assertRaises(ValueError):
            extract_text(b"data", "evil.exe")

    def test_empty_file(self):
        with self.assertRaises(ValueError):
            extract_text(b"", "empty.txt")

    def test_whitespace_only(self):
        with self.assertRaises(ValueError):
            extract_text("   \n  ".encode("utf-8"), "blank.txt")


if __name__ == "__main__":
    unittest.main()
