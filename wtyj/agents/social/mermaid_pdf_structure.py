"""Small ReportLab tagging adapter for Mermaid's fixed PDF flowables.

Adds language, semantic headings/paragraphs/tables and a page parent tree.
This improves logical reading order; it does not certify PDF/UA or WCAG.
ReportLab's built-in fonts and assistive-reader compatibility still need audit.
"""
from contextlib import contextmanager
from functools import partial

from reportlab.pdfbase import pdfdoc
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph as BaseParagraph, Table as BaseTable
from reportlab.platypus import Image as BaseImage, HRFlowable as BaseRule


class Structure:
    def __init__(self, role, parent=None):
        self.role, self.parent = role, parent


class TaggedCanvas(Canvas):
    def __init__(self, *args, language="en", **kwargs):
        super().__init__(*args, **kwargs)
        self._structure_nodes = {}
        self._page_parents = []
        self._current_parents = []
        self._structure_root = pdfdoc.PDFDictionary({"Type": pdfdoc.PDFName("StructTreeRoot")})
        self._structure_root_ref = self._doc.Reference(self._structure_root)
        self._document_node = self._node("Document", self._structure_root_ref)
        self._structure_root["K"] = pdfdoc.PDFArray([self._doc.Reference(self._document_node)])
        self._doc.Catalog.Lang = pdfdoc.PDFString(language)
        self._doc.Catalog.MarkInfo = pdfdoc.PDFDictionary({"Marked": pdfdoc.PDFtrue})
        self._doc.Catalog.StructTreeRoot = self._structure_root
        self._doc.Catalog.ViewerPreferences = pdfdoc.PDFDictionary({"DisplayDocTitle": pdfdoc.PDFtrue})

    def _node(self, role, parent):
        return pdfdoc.PDFDictionary({"Type": pdfdoc.PDFName("StructElem"),
                                     "S": pdfdoc.PDFName(role), "P": parent,
                                     "K": pdfdoc.PDFArray([])})

    def _parent(self, structure):
        if structure is None:
            return self._document_node
        if structure not in self._structure_nodes:
            parent = self._parent(structure.parent)
            node = self._node(structure.role, self._doc.Reference(parent))
            parent["K"].sequence.append(self._doc.Reference(node))
            self._structure_nodes[structure] = node
        return self._structure_nodes[structure]

    @contextmanager
    def marked(self, role, text, structure=None, scope=None):
        parent = self._parent(structure)
        node = self._node(role, self._doc.Reference(parent))
        mcid = len(self._current_parents)
        node["K"] = mcid
        node["Pg"] = self._doc.thisPageRef()
        # ActualText also retains diacritics through standard-font extraction.
        node["ActualText"] = pdfdoc.PDFString(text)
        if scope:
            node["A"] = pdfdoc.PDFDictionary({"O": pdfdoc.PDFName("Table"), "Scope": pdfdoc.PDFName(scope)})
        reference = self._doc.Reference(node)
        parent["K"].sequence.append(reference)
        self._current_parents.append(reference)
        self._code.append(f"/{role} <</MCID {mcid}>> BDC")
        try:
            yield
        finally:
            self._code.append("EMC")

    @contextmanager
    def artifact(self):
        self._code.append("/Artifact BMC")
        try:
            yield
        finally:
            self._code.append("EMC")

    def showPage(self):
        page_index = len(self._page_parents)
        self._page_parents.append(self._current_parents)
        super().showPage()
        page = self._doc.Pages.pages[-1]
        # Extend this page object only, avoiding changes shared by other tenants.
        page.__NoDefault__ = [*page.__NoDefault__, "StructParents", "Tabs"]
        page.StructParents = page_index
        page.Tabs = pdfdoc.PDFName("S")
        self._current_parents = []

    def save(self):
        if self._code:
            self.showPage()
        nums = []
        for index, parents in enumerate(self._page_parents):
            nums.extend([index, pdfdoc.PDFArray(parents)])
        tree = pdfdoc.PDFDictionary({"Nums": pdfdoc.PDFArray(nums)})
        self._structure_root["ParentTree"] = self._doc.Reference(tree)
        self._structure_root["ParentTreeNextKey"] = len(self._page_parents)
        super().save()


def canvas_for(language):
    return partial(TaggedCanvas, language=language)


class Paragraph(BaseParagraph):
    def __init__(self, *args, role=None, structure=None, scope=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.pdf_role = role or ("H1" if self.style.name in {"QuoteTitle", "ReceiptHeading"}
                                 else "H2" if self.style.name == "QuoteSection" else "P")
        self.pdf_structure, self.pdf_scope = structure, scope

    def draw(self):
        with self.canv.marked(self.pdf_role, self.getPlainText(), self.pdf_structure, self.pdf_scope):
            super().draw()

    def split(self, *args):
        parts = super().split(*args)
        for part in parts:
            part.pdf_role, part.pdf_structure, part.pdf_scope = self.pdf_role, self.pdf_structure, self.pdf_scope
        return parts


class Table(BaseTable):
    def _drawBkgrnd(self):
        with self.canv.artifact():
            super()._drawBkgrnd()

    def _drawLines(self):
        with self.canv.artifact():
            super()._drawLines()


class Image(BaseImage):
    def draw(self):
        # This photo is decorative branding, with all trip facts in text.
        with self.canv.artifact():
            super().draw()


class HRFlowable(BaseRule):
    def draw(self):
        with self.canv.artifact():
            super().draw()
