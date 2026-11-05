"""A shared-string cell with an empty <v/> is an empty cell, not a crash."""
import io
import zipfile

from infoparser.pipeline import runner
from infoparser.worker import Processed

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
