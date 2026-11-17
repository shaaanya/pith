"""A shared-string cell with an empty <v/> is an empty cell, not a crash."""
import io
import zipfile

from pith.pipeline import runner
from pith.worker import Processed

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def test_empty_shared_string_value_is_an_empty_cell(svc):
    """`<c t="s"><v/></c>` (no index) used to raise TypeError in int(None)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", f'<workbook xmlns="{NS}"/>')
        z.writestr("xl/sharedStrings.xml", f'<sst xmlns="{NS}"><si><t>Name</t></si></sst>')
        z.writestr("xl/worksheets/sheet1.xml", f'<worksheet xmlns="{NS}"><sheetData>'
                   '<row><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v/></c></row>'
                   '</sheetData></worksheet>')
    iid = svc.inbox.submit(adapter="t", file=buf.getvalue(), filename="t.xlsx").id
    assert isinstance(runner.process(svc, iid), Processed)
    row = svc.conn.execute("SELECT locator, text FROM segments").fetchone()
    assert row["locator"] == "sheet=1" and "Name" in row["text"]


def test_bad_shared_string_index_is_an_empty_cell(svc):
    """Negative, non-numeric, fractional or out-of-range indexes never read another cell."""
    cells = "".join(f'<c r="{c}1" t="s"><v>{v}</v></c>' for c, v in
                    zip("BCDE", ("-1", "abc", "1.0", "99")))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", f'<workbook xmlns="{NS}"/>')
        z.writestr("xl/sharedStrings.xml", f'<sst xmlns="{NS}"><si><t>Name</t></si></sst>')
        z.writestr("xl/worksheets/sheet1.xml", f'<worksheet xmlns="{NS}"><sheetData>'
                   f'<row><c r="A1" t="s"><v>0</v></c>{cells}</row></sheetData></worksheet>')
    iid = svc.inbox.submit(adapter="t", file=buf.getvalue(), filename="t.xlsx").id
    assert isinstance(runner.process(svc, iid), Processed)
    text = svc.conn.execute("SELECT text FROM segments").fetchone()["text"]
    assert text.count("Name") == 1
