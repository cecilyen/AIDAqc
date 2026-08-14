"""Minimal dictionary-to-XML helper used by the Bruker metadata parser."""

from xml.sax.saxutils import escape

__author__ = "Pianfetti Maurizio <boymix81@gmail.com>"
__contributors__ = []
__date__ = "$Date: 2007/12/15 11:57:20  $"
__credits__ = """..."""
__version__ = "$Revision: 1.0.0 $"


def is_mapping(value):
    """Return True for dict-like objects without depending on their concrete class."""
    return hasattr(value, "items")


def render_mapping(mapping, level=0):
    """Render a mapping as simple XML tags."""
    xml = []

    for key, value in mapping.items():
        indent = "\t" * level
        if is_mapping(value):
            if value:
                xml.append("%s<%s>\n" % (indent, key))
                xml.append(render_mapping(value, level + 1))
                xml.append("%s</%s>\n" % (indent, key))
            else:
                xml.append("%s<%s></%s>\n" % (indent, key, key))
        else:
            text = "" if value is None else escape(str(value))
            xml.append("%s<%s>%s</%s>\n" % (indent, key, text, key))

    return "".join(xml)


class Dict2XML:
    """Backward-compatible wrapper around render_mapping."""

    def __init__(self):
        self.xml = ""
        self.level = 0

    def setXml(self, xml):
        self.xml = xml

    def setLevel(self, level):
        self.level = level

    def dict2xml(self, mapping):
        self.xml += render_mapping(mapping, self.level)
        return self.xml


def createXML(mapping, xml):
    xmlout = Dict2XML()
    xmlout.setXml(xml)
    return xmlout.dict2xml(mapping)


dict2Xml = createXML


if __name__ == "__main__":
    data = {
        "root": {
            "v1": "",
            "v2": "hi",
            "v3": {"v31": "hi"},
        }
    }
    print(dict2Xml(data, ""))
