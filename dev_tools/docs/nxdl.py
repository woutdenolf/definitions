import os
import re
from collections import OrderedDict
from html import parser as HTMLParser
from pathlib import Path
from typing import List
from typing import Optional

import lxml

from ..globals.directories import get_nxdl_root
from ..globals.errors import NXDLParseError
from ..globals.nxdl import NXDL_NAMESPACE
from ..globals.urls import REPO_URL
from ..utils.github import get_file_contributors_via_api
from ..utils.nxdl_utils import get_inherited_nodes
from ..utils.types import PathLike
from .anchor_list import AnchorRegistry

# controlling the length of progressively more indented sub-node
MIN_COLLAPSE_HINT_LINE_LENGTH = 20
MAX_COLLAPSE_HINT_LINE_LENGTH = 80


class NXClassDocGenerator:
    """Generate documentation in reStructuredText markup
    for a NeXus class definition."""

    _INDENTATION_UNIT = " " * 2

    _CATEGORY_TO_LISTING = {
        "base": "base class",
        "application": "application definition",
    }

    def __init__(self) -> None:
        self._rst_lines = None
        self._reset()

    def _reset(self):
        self._anchor_registry = None
        self._listing_category = None
        self._use_application_defaults = None

    def __call__(
        self, nxdl_file: PathLike, anchor_registry: Optional[AnchorRegistry] = None
    ) -> List[str]:
        self._rst_lines = list()
        self._anchor_registry = anchor_registry
        nxdl_file = Path(nxdl_file)
        if anchor_registry:
            self._anchor_registry.nxdl_file = nxdl_file
        try:
            try:
                self._parse_nxdl_file(nxdl_file)
            except Exception:
                raise NXDLParseError(nxdl_file)
        finally:
            self._reset()
        return self._rst_lines

    def _parse_nxdl_file(self, nxdl_file: Path):
        assert nxdl_file.is_file()
        tree = lxml.etree.parse(str(nxdl_file))
        root = tree.getroot()

        # NXDL_NAMESPACE needs to be a globally unique identifier of
        # the NXDL schema. It needs to match the xmlns attribute
        # in the NXDL definition of the NeXus class.
        ns = {"nx": NXDL_NAMESPACE}

        nxclass_name = root.get("name")
        category = root.attrib["category"]
        title = nxclass_name
        parent_path = "/" + nxclass_name  # absolute path of parent nodes, no trailing /
        if len(nxclass_name) < 2 or nxclass_name[0:2] != "NX":
            raise Exception(
                f'Unexpected class name "{nxclass_name}"; does not start with NX'
            )
        lexical_name = nxclass_name[2:]  # without padding 'NX', for indexing

        self._listing_category = self._CATEGORY_TO_LISTING[category]
        self._use_application_defaults = category == "application"
        self._contribution = nxdl_file.parent.name == "contributed_definitions"

        # print ReST comments and section header
        source = os.path.relpath(nxdl_file, get_nxdl_root())
        self._print(
            f".. auto-generated by {__name__} from the NXDL source {source} -- DO NOT EDIT"
        )

        self._print("")
        self._print(".. index::")
        self._print(f"    ! {nxclass_name} ({self._listing_category})")
        self._print(f"    ! {lexical_name} ({self._listing_category})")
        self._print(
            f"    see: {lexical_name} ({self._listing_category}); {nxclass_name}"
        )
        self._print("")
        self._print(f".. _{nxclass_name}:\n")
        self._print("=" * len(title))
        self._print(title)
        self._print("=" * len(title))

        # print category & parent class
        extends = root.get("extends")
        if extends is None:
            extends = "none"
        else:
            extends = f":ref:`{extends}`"

        # add the contributors as variables to the rst file that will
        nxdl_root = get_nxdl_root()
        rel_path = str(nxdl_file.relative_to(nxdl_root))
        rel_html = str(rel_path).replace(os.sep, "/")
        contribs_dct = get_file_contributors_via_api("definitions", rel_html)
        if contribs_dct is not None:
            self._print("")
            self._print("..")
            self._print("    Contributors List")
            for date_str, contrib_dct in contribs_dct.items():
                date_str = date_str.split("T")[0]
                name = contrib_dct["name"]
                gh_login_nm = contrib_dct["commit_dct"]["committer"]["login"]
                gh_avatar_url = contrib_dct["commit_dct"]["committer"]["avatar_url"]
                self._print("")
                s = "|".join([name, gh_login_nm, gh_avatar_url, date_str])
                self._print(f"    .. |contrib_name| replace:: {s}")

        self._print("")
        self._print("**Status**:\n")
        if self._contribution:
            self._print(
                f"  *{self._listing_category}* (contribution), extends {extends}"
            )
        else:
            self._print(f"  {self._listing_category}, extends {extends}")

        self._print_if_deprecated(ns, root, "")

        # print official description of this class
        self._print("")
        self._print("**Description**:\n")
        self._print_doc_enum("", ns, root, required=True)

        # print symbol list
        node_list = root.xpath("nx:symbols", namespaces=ns)
        self._print("**Symbols**:\n")
        if len(node_list) == 0:
            self._print("  No symbol table\n")
        elif len(node_list) > 1:
            raise Exception(f"Invalid symbol table in {nxclass_name}")
        else:
            self._print_doc_enum("", ns, node_list[0])
            for node in node_list[0].xpath("nx:symbol", namespaces=ns):
                doc = self._get_doc_line(ns, node)
                self._print(f"  **{node.get('name')}**", end="")
                if doc:
                    self._print(f": {doc}", end="")
                self._print("\n")

        # print group references
        self._print("**Groups cited**:")
        node_list = root.xpath("//nx:group", namespaces=ns)
        groups = []
        for node in node_list:
            g = node.get("type")
            if g.startswith("NX") and g not in groups:
                groups.append(g)
        if len(groups) == 0:
            self._print("  none\n")
        else:
            out = [(f":ref:`{g}`") for g in groups]
            txt = ", ".join(sorted(out))
            self._print(f"  {txt}\n")
            out = [
                ("%s (base class); used in %s" % (g, self._listing_category))
                for g in groups
            ]
            txt = ", ".join(out)
            self._print(f".. index:: {txt}\n")

        # print full tree
        self._print("**Structure**:\n")
        for subnode in root.xpath("nx:attribute", namespaces=ns):
            optional = self._get_required_or_optional_text(subnode)
            self._print_attribute(
                ns, "file", subnode, optional, self._INDENTATION_UNIT, parent_path
            )  # FIXME: +"/"+name )
        self._print_full_tree(
            ns, root, nxclass_name, self._INDENTATION_UNIT, parent_path
        )

        self._print_anchor_list()

        # print NXDL source location
        self._print("")
        self._print("**NXDL Source**:")
        nxdl_root = get_nxdl_root()
        rel_path = str(nxdl_file.relative_to(nxdl_root))
        rel_html = str(rel_path).replace(os.sep, "/")
        self._print(f"  {REPO_URL}/{rel_html}")

        return self._rst_lines

    def _print_anchor_list(self):
        """Print the list of hypertext anchors."""
        if not self._anchor_registry:
            return
        anchors = self._anchor_registry.flush_anchor_buffer()
        if not anchors:
            return

        self._print("")
        self._print("Hypertext Anchors")
        self._print("-----------------\n")
        self._print(
            "List of hypertext anchors for all groups, fields,\n"
            "attributes, and links defined in this class.\n\n"
        )

        def sorter(key):
            return key.lower()

        rst = [f"* :ref:`{ref} <{ref}>`" for ref in sorted(anchors, key=sorter)]

        self._print("\n".join(rst))

    @staticmethod
    def _format_type(node):
        typ = node.get("type", ":ref:`NX_CHAR <NX_CHAR>`")  # per default
        if typ.startswith("NX_"):
            typ = f":ref:`{typ} <{typ}>`"
        return typ

    @staticmethod
    def _format_units(node):
        units = node.get("units", "")
        if not units:
            return ""
        if units.startswith("NX_"):
            units = rf"\ :ref:`{units} <{units}>`"
        return f" {{units={units}}}"

    @staticmethod
    def _get_doc_blocks(ns, node):
        docnodes = node.xpath("nx:doc", namespaces=ns)
        if docnodes is None or len(docnodes) == 0:
            return ""
        if len(docnodes) > 1:
            raise Exception(
                f"Too many doc elements: line {node.sourceline}, {Path(node.base).name}"
            )
        docnode = docnodes[0]

        # be sure to grab _all_ content in the documentation
        # it might look like XML
        s = lxml.etree.tostring(
            docnode, pretty_print=True, method="c14n", with_comments=False
        ).decode("utf-8")
        m = re.search(r"^<doc[^>]*>\n?(.*)\n?</doc>$", s, re.DOTALL)
        if not m:
            raise Exception(f"unexpected docstring [{s}] ")
        text = m.group(1)

        # substitute HTML entities in markup: "<" for "&lt;"
        # thanks: http://stackoverflow.com/questions/2087370/decode-html-entities-in-python-string
        htmlparser = HTMLParser.HTMLParser()
        try:  # see #661
            import html

            text = html.unescape(text)
        except (ImportError, AttributeError):
            text = htmlparser.unescape(text)

        # Blocks are separated by whitelines
        blocks = re.split("\n\\s*\n", text)
        if len(blocks) == 1 and len(blocks[0].splitlines()) == 1:
            return [blocks[0].rstrip().lstrip()]

        # Indentation must be given by first line
        m = re.match(r"(\s*)(\S+)", blocks[0])
        if not m:
            return [""]
        indent = m.group(1)

        # Remove common indentation as determined from first line
        if indent == "":
            raise Exception(
                "Missing initial indentation in <doc> of %s [%s]"
                % (node.get("name"), blocks[0])
            )

        out_blocks = []
        for block in blocks:
            lines = block.rstrip().splitlines()
            out_lines = []
            for line in lines:
                if line[: len(indent)] != indent:
                    raise Exception(
                        'Bad indentation in <doc> of %s [%s]: expected "%s" found "%s".'
                        % (
                            node.get("name"),
                            block,
                            re.sub(r"\t", "\\\\t", indent),
                            re.sub(r"\t", "\\\\t", line),
                        )
                    )
                out_lines.append(line[len(indent) :])
            out_blocks.append("\n".join(out_lines))
        return out_blocks

    def _get_doc_line(self, ns, node):
        blocks = self._get_doc_blocks(ns, node)
        if len(blocks) == 0:
            return ""
        if len(blocks) > 1:
            raise Exception(f"Unexpected multi-paragraph doc [{'|'.join(blocks)}]")
        return re.sub(r"\n", " ", blocks[0])

    def _get_minOccurs(self, node):
        """
        get the value for the ``minOccurs`` attribute

        :param obj node: instance of lxml.etree._Element
        :returns str: value of the attribute (or its default)
        """
        # TODO: can we improve on the default by examining nxdl.xsd?
        minOccurs_default = str(int(self._use_application_defaults))
        minOccurs = node.get("minOccurs", minOccurs_default)
        return minOccurs

    def _get_required_or_optional_text(self, node):
        """
        make clear if a reported item is required or optional

        :param obj node: instance of lxml.etree._Element
        :returns: formatted text
        """
        tag = node.tag.split("}")[-1]
        if tag in ("field", "group"):
            optional_default = not self._use_application_defaults
            optional = node.get("optional", optional_default) in (True, "true", "1", 1)
            recommended = node.get("recommended", None) in (True, "true", "1", 1)
            minOccurs = self._get_minOccurs(node)
            if recommended:
                optional_text = "(recommended) "
            elif minOccurs in ("0", 0) or optional:
                optional_text = "(optional) "
            elif minOccurs in ("1", 1):
                optional_text = "(required) "
            else:
                # this is unexpected and remarkable
                # TODO: add a remark to the log
                optional_text = f"(``minOccurs={str(minOccurs)}``) "
        elif tag in ("attribute",):
            optional_default = not self._use_application_defaults
            optional = node.get("optional", optional_default) in (True, "true", "1", 1)
            recommended = node.get("recommended", None) in (True, "true", "1", 1)
            optional_text = {True: "(optional) ", False: "(required) "}[optional]
            if recommended:
                optional_text = "(recommended) "
        else:
            optional_text = "(unknown tag: " + str(tag) + ") "
        return optional_text

    def _analyze_dimensions(self, ns, parent) -> str:
        """These are the different dimensions that can occur:

        1. Fixed rank

            <dimensions rank="dataRank">
            <dim index="1" value="a" />
            <dim index="2" value="b" />
            <dim index="3" value="c" />
            </dimensions>

        2. Variable rank because of optional dimensions

            <dimensions rank="dataRank">
            <dim index="1" value="a" />
            <dim index="2" value="b" />
            <dim index="3" value="c" />
            <dim index="4" value="d" required="false"/>
            </dimensions>

        3. Variable rank because no dimensions specified

            <dimensions rank="dataRank">
            </dimensions>

        4. Rank and dimensions equal to that of another field called `field_name`

            <dimensions rank="dataRank">
            <dim index="1" ref="field_name" />
            </dimensions>
        """
        node_list = parent.xpath("nx:dimensions", namespaces=ns)
        if len(node_list) != 1:
            return ""
        node = node_list[0]
        node_list = node.xpath("nx:dim", namespaces=ns)

        dims = []
        optional = False
        for subnode in node_list:
            # Dimension index (starts from index 1)
            index = subnode.get("index", "")
            if not index.isdigit():
                raise RuntimeError("A dimension must have an index")
            index = int(index)
            if index <= 0:
                # No longer permitted
                raise RuntimeError(
                    "A dimension's index must be a positive integer (>=1)"
                )

            # Expand dimensions when needed
            index -= 1
            nadd = max(index - len(dims) + 1, 0)
            if nadd:
                dims += ["."] * nadd

            # Dimension symbol
            dim = subnode.get("value")  # integer or symbol from the table
            if not dim:
                ref = subnode.get("ref")
                if ref:
                    return (
                        f" (Rank: same as field {ref}, Dimensions: same as field {ref})"
                    )
                dim = "."  # dimension has no symbol

            # Dimension might be optional
            if subnode.get("required", "true").lower() == "false":
                optional = True
            elif optional:
                raise RuntimeError(
                    "A required dimension cannot come after an optional dimension"
                )
            if optional:
                dim = f"[{dim}]"

            dims[index] = dim

        # When the rank is missing, set to the number of dimensions when
        # there are dimensions specified and none of them are optional.
        ndims = len(dims)
        rank = node.get("rank", None)
        if rank is None and not optional and ndims:
            rank = str(ndims)

        # Validate rank and dimensions
        rank_is_fixed = rank and rank.isdigit()
        if optional and rank_is_fixed:
            raise RuntimeError("A fixed rank cannot have optional dimensions")
        if rank_is_fixed and ndims and int(rank) != ndims:
            raise RuntimeError(
                "The rank and the number of dimensions do not correspond"
            )

        # Omit rank and/or dimensions when not specified
        if rank and dims:
            dims = ", ".join(dims)
            return f" (Rank: {rank}, Dimensions: [{dims}])"
        elif rank:
            return f" (Rank: {rank})"
        elif dims:
            dims = ", ".join(dims)
            return f" (Dimensions: [{dims}])"
        return ""

    def _hyperlink_target(self, parent_path, name, nxtype):
        """Return internal hyperlink target for HTML anchor."""
        if nxtype == "attribute":
            sep = "@"
        else:
            sep = "/"
        target = f"{parent_path}{sep}{name}-{nxtype}"
        if self._anchor_registry:
            self._anchor_registry.add(target)
        return f".. _{target}:\n"

    def _print_enumeration(self, indent, ns, parent):
        node_list = parent.xpath("nx:item", namespaces=ns)
        if len(node_list) == 0:
            return ""

        if len(node_list) == 1:
            self._print(f"{indent}Obligatory value:", end="")
        else:
            self._print(f"{indent}Any of these values:", end="")

        docs = OrderedDict()
        for item in node_list:
            name = item.get("value")
            docs[name] = self._get_doc_line(ns, item)

        ENUMERATION_INLINE_LENGTH = 60

        def show_as_typed_text(msg):
            return f"``{msg}``"

        oneliner = " | ".join(map(show_as_typed_text, docs.keys()))
        if (
            any(doc for doc in docs.values())
            or len(oneliner) > ENUMERATION_INLINE_LENGTH
        ):
            # print one item per line
            self._print("\n")
            for name, doc in docs.items():
                self._print(f"{indent}  * {show_as_typed_text(name)}", end="")
                if doc:
                    self._print(f": {doc}", end="")
                self._print("\n")
        else:
            # print all items in one line
            self._print(f" {oneliner}")
        self._print("")

    def _print_doc(self, indent, ns, node, required=False):
        blocks = self._get_doc_blocks(ns, node)
        if len(blocks) == 0:
            if required:
                raise Exception("No documentation for: " + node.get("name"))
            self._print("")
        else:
            for block in blocks:
                for line in block.splitlines():
                    self._print(f"{indent}{line}")
                self._print()

    def long_doc(self, ns, node, left_margin):
        length = 0
        line = "documentation"
        fnd = False
        blocks = self._get_doc_blocks(ns, node)
        max_characters = max(
            MIN_COLLAPSE_HINT_LINE_LENGTH, (MAX_COLLAPSE_HINT_LINE_LENGTH - left_margin)
        )
        for block in blocks:
            lines = block.splitlines()
            length += len(lines)
            for single_line in lines:
                if len(single_line) > 2 and single_line[0] != "." and not fnd:
                    fnd = True
                    line = single_line[:max_characters]
        return (length, line, blocks)

    def _print_doc_enum(self, indent, ns, node, required=False):
        collapse_indent = indent
        node_list = node.xpath("nx:enumeration", namespaces=ns)
        (doclen, line, blocks) = self.long_doc(ns, node, len(indent))
        if len(node_list) + doclen > 1:
            collapse_indent = f"{indent}    "
            self._print(f"{indent}{self._INDENTATION_UNIT}.. collapse:: {line} ...\n")
        self._print_doc(
            collapse_indent + self._INDENTATION_UNIT, ns, node, required=required
        )
        if len(node_list) == 1:
            self._print_enumeration(
                collapse_indent + self._INDENTATION_UNIT, ns, node_list[0]
            )

    def _print_attribute(self, ns, kind, node, optional, indent, parent_path):
        name = node.get("name")
        index_name = name
        self._print(
            f"{indent}" f"{self._hyperlink_target(parent_path, name, 'attribute')}"
        )
        self._print(f"{indent}.. index:: {index_name} ({kind} attribute)\n")
        self._print(
            f"{indent}**@{name}**: {optional}{self._format_type(node)}{self._format_units(node)} {self.get_first_parent_ref(f'{parent_path}/{name}', 'attribute')}\n"
        )
        self._print_doc_enum(indent, ns, node)

    def _print_if_deprecated(self, ns, node, indent):
        deprecated = node.get("deprecated", None)
        if deprecated is not None:
            self._print(f"\n{indent}.. index:: deprecated\n")
            self._print(f"\n{indent}**DEPRECATED**: {deprecated}\n")

    def _print_full_tree(self, ns, parent, name, indent, parent_path):
        """
        recursively print the full tree structure

        :param dict ns: dictionary of namespaces for use in XPath expressions
        :param lxml_element_node parent: parent node to be documented
        :param str name: name of elements, such as NXentry/NXuser
        :param indent: to keep track of indentation level
        :param parent_path: NX class path of parent nodes
        """
        for node in parent.xpath("nx:field", namespaces=ns):
            name = node.get("name")
            index_name = name
            dims = self._analyze_dimensions(ns, node)

            optional_text = self._get_required_or_optional_text(node)
            self._print(f"{indent}{self._hyperlink_target(parent_path, name, 'field')}")
            self._print(f"{indent}.. index:: {index_name} (field)\n")
            self._print(
                f"{indent}**{name}**: "
                f"{optional_text}"
                f"{self._format_type(node)}"
                f"{dims}"
                f"{self._format_units(node)}"
                f" {self.get_first_parent_ref(f'{parent_path}/{name}', 'field')}"
                "\n"
            )

            self._print_if_deprecated(ns, node, indent + self._INDENTATION_UNIT)
            self._print_doc_enum(indent, ns, node)

            for subnode in node.xpath("nx:attribute", namespaces=ns):
                optional = self._get_required_or_optional_text(subnode)
                self._print_attribute(
                    ns,
                    "field",
                    subnode,
                    optional,
                    indent + self._INDENTATION_UNIT,
                    parent_path + "/" + name,
                )

        for node in parent.xpath("nx:group", namespaces=ns):
            name = node.get("name", "")
            typ = node.get("type", "untyped (this is an error; please report)")

            optional_text = self._get_required_or_optional_text(node)
            if typ.startswith("NX"):
                if name == "":
                    name = typ.lstrip("NX").upper()
                typ = f":ref:`{typ}`"
            hTarget = self._hyperlink_target(parent_path, name, "group")
            # target = hTarget.replace(".. _", "").replace(":\n", "")
            # TODO: https://github.com/nexusformat/definitions/issues/1057
            self._print(f"{indent}{hTarget}")
            self._print(
                f"{indent}**{name}**: {optional_text}{typ} {self.get_first_parent_ref(f'{parent_path}/{name}', 'group')}\n"
            )

            self._print_if_deprecated(ns, node, indent + self._INDENTATION_UNIT)
            self._print_doc_enum(indent, ns, node)

            for subnode in node.xpath("nx:attribute", namespaces=ns):
                optional = self._get_required_or_optional_text(subnode)
                self._print_attribute(
                    ns,
                    "group",
                    subnode,
                    optional,
                    indent + self._INDENTATION_UNIT,
                    parent_path + "/" + name,
                )

            nodename = "%s/%s" % (name, node.get("type"))
            self._print_full_tree(
                ns,
                node,
                nodename,
                indent + self._INDENTATION_UNIT,
                parent_path + "/" + name,
            )

        for node in parent.xpath("nx:link", namespaces=ns):
            name = node.get("name")
            self._print(f"{indent}{self._hyperlink_target(parent_path, name, 'link')}")
            self._print(
                f"{indent}**{name}**: "
                ":ref:`link<Design-Links>` "
                f"(suggested target: ``{node.get('target')}``)"
                "\n"
            )
            self._print_doc_enum(indent, ns, node)

    def _print(self, *args, end="\n"):
        # TODO: change instances of \t to proper indentation
        self._rst_lines.append(" ".join(args) + end)

    def get_first_parent_ref(self, path, tag):
        nx_name = path[1 : path.find("/", 1)]
        path = path[path.find("/", 1) :]

        try:
            parents = get_inherited_nodes(path, nx_name)[2]
        except FileNotFoundError:
            return ""
        if len(parents) > 1:
            parent = parents[1]
            parent_path = parent_display_name = parent.attrib["nxdlpath"]
            parent_path_segments = parent_path[1:].split("/")
            parent_def_name = parent.attrib["nxdlbase"][
                parent.attrib["nxdlbase"]
                .rfind("/") : parent.attrib["nxdlbase"]
                .rfind(".nxdl")
            ]

            # Case where the first parent is a base_class
            if parent_path_segments[0] == "":
                return ""

            # special treatment for NXnote@type
            if (
                tag == "attribute"
                and parent_def_name == "/NXnote"
                and parent_path == "/type"
            ):
                return ""

            if tag == "attribute":
                pos_of_right_slash = parent_path.rfind("/")
                parent_path = (
                    parent_path[:pos_of_right_slash]
                    + "@"
                    + parent_path[pos_of_right_slash + 1 :]
                )
            parent_display_name = f"{parent_def_name[1:]}{parent_path}"
            return f":ref:`⤆ </{parent_display_name}-{tag}>`"
        return ""
