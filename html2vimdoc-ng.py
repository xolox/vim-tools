#!/usr/bin/env python

# Missing features:
# TODO Generate table of contents from headings.
# TODO Find tag definitions in headings and mark them.
# TODO Find tag references in text and mark them.
#
# Finding the right abstractions:
# FIXME Quirky mix of classes and functions?
# FIXME Node joining is all over the place... What if every node can indicate how it wants to be joined with other nodes?

"""
html2vimdoc
===========

The ``html2vimdoc`` module takes HTML documents and converts them to Vim help
files. It tries to produce Vim help files that are a pleasure to read while
preserving as much information as possible from the original HTML document.
Here are some of the design goals of ``html2vimdoc``:

- Flexible HTML parsing powered by ``BeautifulSoup``;
- Support for nested block level elements, e.g. nested lists;
- Automatically generates a table of contents based on headings;
- Translates hyper links into external references (which are included in an
  appendix) and rewrites hyper links that point to Vim's online documentation
  into help tags which can be followed inside Vim.

How does it work?
-----------------

The ``html2vimdoc`` module works in three phases:

1. It parses the HTML document using ``BeautifulSoup``;
2. It converts the parse tree produced by ``BeautifulSoup`` into a
   simpler format that makes it easier to convert to a Vim help file;
3. It generates a Vim help file by walking through the simplified parse tree
   using recursion.
"""

# Standard library modules.
import collections
import logging
import re
import textwrap
import urllib

# External dependency, install with:
#   sudo apt-get install python-beautifulsoup
#   pip install beautifulsoup
from BeautifulSoup import BeautifulSoup, NavigableString

# External dependency, install with:
#  pip install coloredlogs
import coloredlogs

# External dependency, bundled because it's not on PyPi.
import libs.soupselect as soupselect

# Sensible defaults (you probably shouldn't change these).
TEXT_WIDTH = 79
SHIFT_WIDTH = 2

# Initialize the logging subsystem.
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
logger.addHandler(coloredlogs.ColoredStreamHandler())

# Mapping of HTML element names to custom Node types.
name_to_type_mapping = {}

def main():
    filename = 'test.html'
    filename = 'demo/apr-0.17.html'
    filename = 'demo/lpeg-0.10.html'
    with open(filename) as handle:
        html = handle.read()
        html = re.sub(r'test coverage: \S+', '', html)
        output = html2vimdoc(html, filename='lpeg.txt', selectors_to_ignore=['h3 a[class=anchor]'])
        print output.encode('utf-8')

def html2vimdoc(html, title='', filename='', content_selector='#content', selectors_to_ignore=[], modeline='vim: ft=help'):
    """
    Convert HTML documents to the Vim help file format.
    """
    html = decode_hexadecimal_entities(html)
    tree = BeautifulSoup(html, convertEntities=BeautifulSoup.ALL_ENTITIES)
    title = select_title(tree, title)
    ignore_given_selectors(tree, selectors_to_ignore)
    root = find_root_node(tree, content_selector)
    simple_tree = simplify_tree(root)
    shift_headings(simple_tree)
    find_references(simple_tree)
    # XXX Write the AST to disk (for debugging).
    with open('tree.py', 'w') as handle:
        handle.write("%r\n" % simple_tree)
    vimdoc = simple_tree.render(indent=0)
    output = list(flatten(vimdoc))
    deduplicate_delimiters(output)
    # Render the final text.
    vimdoc = u"".join(unicode(v) for v in output)
    # Add the first line with the file tag and/or document title?
    if title or filename:
        firstline = []
        if filename:
            firstline.append("*%s*" % filename)
        if title:
            firstline.append(title)
        vimdoc = "%s\n\n%s" % ("  ".join(firstline), vimdoc)
    # Add a mode line at the end of the document.
    if modeline and not modeline.isspace():
        vimdoc += "\n\n" + modeline
    return vimdoc

def select_title(tree, title):
    if not title:
        elements = tree.findAll('title')
        if elements:
            title = ''.join(elements[0].findAll(text=True))
    return title

def deduplicate_delimiters(output):
    # Deduplicate redundant block delimiters from the rendered Vim help text.
    i = 0
    while i < len(output) - 1:
        if isinstance(output[i], OutputDelimiter) and isinstance(output[i + 1], OutputDelimiter):
            if output[i].string.isspace() and not output[i + 1].string.isspace():
                output.pop(i)
                continue
            elif output[i + 1].string.isspace() and not output[i].string.isspace():
                output.pop(i + 1)
                continue
            elif len(output[i].string) < len(output[i + 1].string):
                output.pop(i)
                continue
            elif len(output[i].string) > len(output[i + 1].string):
                output.pop(i + 1)
                continue
            elif output[i].string.isspace():
                output.pop(i)
                continue
        i += 1
    # Strip leading block delimiters.
    while output and isinstance(output[0], OutputDelimiter) and output[0].string.isspace():
        output.pop(0)
    # Strip trailing block delimiters.
    while output and isinstance(output[-1], OutputDelimiter) and output[-1].string.isspace():
        output.pop(-1)

def decode_hexadecimal_entities(html):
    """
    Based on my testing BeautifulSoup doesn't support hexadecimal HTML
    entities, so we have to decode them ourselves :-(
    """
    # If we happen to decode an entity into one of these characters, we
    # should never insert it literally into the HTML because we'll screw
    # up the syntax.
    unsafe_to_decode = {
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&apos;',
            '&': '&amp;',
    }
    def decode_entity(match):
        character = chr(int(match.group(1), 16))
        return unsafe_to_decode.get(character, character)
    return re.sub(r'&#x([0-9A-Fa-f]+);', decode_entity, html)

def find_root_node(tree, selector):
    """
    Given a document tree generated by BeautifulSoup, find the most
    specific document node that doesn't "lose any information" (i.e.
    everything that we want to be included in the Vim help file) while
    ignoring as much fluff as possible (e.g. headers, footers and
    navigation menus included in the original HTML document).
    """
    # Try to find the root node using a CSS selector provided by the caller.
    matches = soupselect.select(tree, selector)
    if matches:
        return matches[0]
    # Otherwise we'll fall back to the <body> element.
    try:
        return tree.html.body
    except:
        # Don't break when html.body doesn't exist.
        return tree

def ignore_given_selectors(tree, selectors_to_ignore):
    """
    Remove all HTML elements matching any of the CSS selectors provided by
    the caller from the parse tree generated by BeautifulSoup.
    """
    for selector in selectors_to_ignore:
        for element in soupselect.select(tree, selector):
            element.extract()

def simplify_tree(tree):
    """
    Simplify the tree generated by BeautifulSoup into something we can
    easily generate a Vim help file from.
    """
    return simplify_node(tree)

def simplify_node(html_node):
    """
    Recursive function to simplify parse trees generated by BeautifulSoup into
    something we can more easily convert into HTML.
    """
    # First we'll get text nodes out of the way since they're very common.
    if isinstance(html_node, NavigableString):
        text = html_node.string
        if text and not text.isspace():
            logger.debug("Mapping text node: %r", text)
            return Text(text=text)
        # Empty text nodes are pruned from the tree.
        return None
    # Now we deal with all of the known & supported HTML elements.
    name = getattr(html_node, 'name', None)
    logger.debug("Trying to map HTML element <%s> ..", name)
    if name in name_to_type_mapping:
        mapped_type = name_to_type_mapping[name]
        logger.debug("Found a mapped type: %s", mapped_type.__name__)
        return mapped_type.parse(html_node)
    # Finally we improvise, trying not to lose information.
    logger.warn("Not a supported element, improvising ..")
    return simplify_children(html_node)

def simplify_children(node):
    """
    Simplify the child nodes of the given node taken from a parse tree
    generated by BeautifulSoup.
    """
    contents = []
    for child in getattr(node, 'contents', []):
        simplified_child = simplify_node(child)
        if simplified_child:
            contents.append(simplified_child)
    if is_block_level(contents):
        logger.debug("Sequence contains some block level elements")
        return BlockLevelSequence(contents=contents)
    else:
        logger.debug("Sequence contains only inline elements")
        return InlineSequence(contents=contents)

def shift_headings(root):
    """
    Perform an intermediate pass over the simplified parse tree to shift
    headings in such a way that top level headings have level 1.
    """
    # Find the largest headings (lowest level).
    min_level = None
    logger.debug("Finding largest headings ..")
    for node in walk_tree(root, Heading):
        if min_level is None:
            min_level = node.level
        elif node.level < min_level:
            min_level = node.level
    if min_level is None:
        logger.debug("HTML document doesn't contain any headings?")
        return
    else:
        logger.debug("Largest headings have level %i.", min_level)
    # Shift the headings if necessary.
    if min_level > 1:
        to_subtract = min_level - 1
        logger.debug("Shifting headings by %i levels.", to_subtract)
        for node in walk_tree(root, Heading):
            node.level -= to_subtract

def find_references(root):
    """
    Scan the document tree for hyper links. Each hyper link is given a unique
    number so that it can be referenced inside the Vim help file. A new section
    is appended to the tree which lists an overview of all references to hyper
    links extracted from the HTML document.
    """
    # Mapping of hyper link targets to "Reference" objects.
    by_target = {}
    # Ordered list of "Reference" objects.
    by_reference = []
    logger.debug("Scanning parse tree for hyper links ..")
    for node in walk_tree(root, HyperLink):
        if not node.target:
            continue
        target = urllib.unquote(node.target)
        # Exclude relative URLs and literal URLs from list of references.
        if '://' not in target or target == node.text:
            continue
        # Make sure we don't duplicate references.
        if target in by_target:
            r = by_target[target]
        else:
            # TODO The "Reference" objects feel a bit arbitrary, isn't there a better abstraction?
            number = len(by_reference) + 1
            logger.debug("Extracting reference #%i to %s ..", number, target)
            r = Reference(number=number, target=target)
            by_reference.append(r)
            by_target[target] = r
        node.reference = r
    logger.debug("Found %i hyper links in parse tree.", len(by_reference))
    if by_reference:
        logger.debug("Generating 'References' section ..")
        root.contents.append(Heading(level=1, contents=[Text(text="References")]))
        root.contents.extend(by_reference)

def walk_tree(root, *node_types):
    """
    Return a list of nodes (optionally filtered by type) ordered by the
    original document order (i.e. the left to right, top to bottom reading
    order of English text).
    """
    ordered_nodes = []
    def recurse(node):
        if not (node_types and not isinstance(node, node_types)):
            ordered_nodes.append(node)
        for child in getattr(node, 'contents', []):
            recurse(child)
    recurse(root)
    return ordered_nodes

# Objects to encapsulate output text with a bit of state.

class OutputDelimiter(object):

    def __init__(self, string):
        self.string = string

    def __unicode__(self):
        return self.string

    def __repr__(self):
        return "OutputDelimiter(string=%r)" % self.string

# Decorator for abstract syntax tree nodes.

def html_element(*element_names):
    """
    Decorator to associate AST nodes and HTML nodes at the point where the AST
    node is defined.
    """
    def wrap(c):
        for name in element_names:
            name_to_type_mapping[name] = c
        return c
    return wrap

# Abstract parse tree nodes.

class Node(object):

    """
    Abstract superclass for all parse tree nodes.
    """

    def __init__(self, **kw):
        """
        Short term hack for prototyping :-).
        """
        self.__dict__ = kw

    def __iter__(self):
        """
        Short term hack to make it easy to walk the tree.
        """
        return iter(getattr(self, 'contents', []))

    def __repr__(self):
        """
        Dumb but useful representation of parse tree for debugging purposes.
        """
        nodes = [repr(n) for n in self.contents]
        if not nodes:
            contents = ""
        elif len(nodes) == 1:
            contents = nodes[0]
        else:
            contents = "\n" + ",\n".join(nodes)
        return "%s(%s)" % (self.__class__.__name__, contents)

    @classmethod
    def parse(cls, html_node):
        """
        Default parse behavior: Just simplify any child nodes.
        """
        return cls(contents=simplify_children(html_node))

class BlockLevelNode(Node):
    """
    Abstract superclass for all block level parse tree nodes. Block level nodes
    are the nodes which take care of indentation and line wrapping by
    themselves.
    """
    start_delimiter = OutputDelimiter('\n\n')
    end_delimiter = OutputDelimiter('\n\n')

class InlineNode(Node):
    """
    Abstract superclass for all inline parse tree nodes. Inline nodes are the
    nodes which are subject to indenting and line wrapping by the block level
    nodes that contain them.
    """
    pass

# Concrete parse tree nodes.

class BlockLevelSequence(BlockLevelNode):

    """
    A sequence of one or more block level nodes.
    """

    def render(self, **kw):
        text = join_blocks(self.contents, **kw)
        return [self.start_delimiter, text, self.end_delimiter]

@html_element('h1', 'h2', 'h3', 'h4', 'h5', 'h6')
class Heading(BlockLevelNode):

    """
    Block level node to represent headings. Maps to the HTML elements ``<h1>``
    to ``<h6>``, however Vim help files have only two levels of headings so
    during conversion some information about the structure of the original
    document is lost.
    """

    @staticmethod
    def parse(html_node):
        return Heading(level=int(html_node.name[1]),
                       contents=simplify_children(html_node))

    def render(self, **kw):
        # Join the inline child nodes together into a single string.
        text = join_inline(self.contents, **kw)
        # Wrap the heading's text. The two character difference is " ~", the
        # suffix used to mark Vim help file headings.
        prefix = ' ' * kw['indent']
        suffix = ' ~'
        width = TEXT_WIDTH - len(prefix) - len(suffix)
        lines = [prefix + l + suffix for l in textwrap.wrap(text, width=width)]
        # Add a line with the marker symbol for headings, repeated on the full
        # line, at the top of the heading.
        lines.insert(0, ('=' if self.level == 1 else '-') * 79)
        return [self.start_delimiter, "\n".join(lines), self.end_delimiter]

@html_element('p')
class Paragraph(BlockLevelNode):

    """
    Block level node to represent paragraphs of text.
    Maps to the HTML element ``<p>``.
    """

    def render(self, **kw):
        return [self.start_delimiter, join_inline(self.contents, **kw), self.end_delimiter]

@html_element('pre')
class PreformattedText(BlockLevelNode):

    """
    Block level node to represent preformatted text.
    Maps to the HTML element ``<pre>``.
    """

    # Vim help file markers for preformatted text.
    start_delimiter = OutputDelimiter('\n>\n')
    end_delimiter = OutputDelimiter('\n<\n')

    @staticmethod
    def parse(html_node):
        # This is the easiest way to get all of the text in the preformatted
        # block while ignoring HTML elements (what would we do with them?).
        text = ''.join(html_node.findAll(text=True))
        # Remove common indentation from the original text.
        text = textwrap.dedent(text)
        # Remove leading/trailing empty lines.
        lines = text.splitlines()
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop(-1)
        return PreformattedText(text="\n".join(lines))

    @property
    def contents(self):
        return [self.text]

    def render(self, **kw):
        prefix = ' ' * max(kw['indent'], 2)
        text = "\n".join(prefix + l for l in self.text.splitlines())
        return [self.start_delimiter, text, self.end_delimiter]

@html_element('ul', 'ol')
class List(BlockLevelNode):

    """
    Block level node to represent ordered and unordered lists.
    Maps to the HTML elements ``<ol>`` and ``<ul>``.
    """

    @staticmethod
    def parse(html_node):
        children = simplify_children(html_node)
        node = List(ordered=(html_node.name=='ol'),
                    contents=children)
        # Make it possible to get from the items (children) to the list (parent).
        for child in children:
            child.parent = node
        return node

    def render(self, **kw):
        # First pass: Render the child nodes and pick the right delimiter.
        items = []
        delimiter = OutputDelimiter('\n')
        for node in self.contents:
            if isinstance(node, ListItem):
                text = node.render(number=len(items) + 1, **kw)
                items.append(text)
                if any('\n' in s for s in text if not isinstance(s, OutputDelimiter)):
                    delimiter = OutputDelimiter('\n\n')
        # Second pass: Combine the delimiters & rendered child nodes.
        output = [self.start_delimiter]
        for i, item in enumerate(items):
            if i > 0:
                output.append(delimiter)
            output.extend(item)
        output.append(self.end_delimiter)
        return output

@html_element('li')
class ListItem(BlockLevelNode):

    """
    Block level node to represent list items.
    Maps to the HTML element ``<li>``.
    """

    def render(self, number, **kw):
        # Get the original prefix (indent).
        prefix = ' ' * kw['indent']
        # Append the list item bullet.
        if self.parent.ordered:
            prefix += '%i. ' % number
        else:
            prefix += '- '
        # Update indent for child nodes.
        kw['indent'] = len(prefix)
        # Render the child node(s).
        text = join_smart(self.contents, **kw)
        # Make sure we're dealing with a list of output delimiters and text.
        if not isinstance(text, list):
            text = [text]
        # Ignore (remove) any leading output delimiters from the
        # text (only when the delimiter itself is whitespace).
        while text and isinstance(text[0], OutputDelimiter) and text[0].string.isspace():
            text.pop(0)
        # Remove leading indent from first text node.
        if text and isinstance(text[0], (str, unicode)):
            for i in xrange(len(prefix)):
                if text[0] and text[0][0].isspace():
                    text[0] = text[0][1:]
        # Prefix the list item bullet.
        return [self.start_delimiter, prefix] + text + [self.end_delimiter]

@html_element('table')
class Table(BlockLevelNode):

    """
    Block level node to represent tabular data.
    Maps to the HTML element ``<table>``.
    """

    def render(self, **kw):
        # TODO Parse and render tabular data.
        return ''

class Reference(BlockLevelNode):

    """
    Block level node to represent a reference to a hyper link.
    """

    start_delimiter = OutputDelimiter('\n')
    end_delimiter = OutputDelimiter('\n')

    def __repr__(self):
        return "Reference(number=%i, target=%r)" % (self.number, self.target)

    def render(self, **kw):
        text = "[%i] %s" % (self.number, self.target)
        return [self.start_delimiter, text, self.end_delimiter]

class InlineSequence(InlineNode):

    """
    Inline node to represent a sequence of one or more inline nodes.
    """

    def render(self, **kw):
        return join_inline(self.contents, **kw)

@html_element('a')
class HyperLink(InlineNode):

    """
    Inline node to represent hyper links.
    Maps to the HTML element ``<a>``.
    """

    @staticmethod
    def parse(html_node):
        return HyperLink(text=''.join(html_node.findAll(text=True)),
                         target=html_node.get('href', ''))

    def __repr__(self):
        return "HyperLink(text=%r, target=%r, reference=%r)" % (self.text, self.target, getattr(self, 'reference', None))

    def render(self, **kw):
        if hasattr(self, 'reference'):
            return "%s [%i]" % (self.text, self.reference.number)
        else:
            return self.text

class Text(InlineNode):

    """
    Inline node to represent a sequence of text.
    """

    @property
    def contents(self):
        return [self.text]

    def render(self, **kw):
        return self.text

def is_block_level(contents):
    """
    Return True if any of the nodes in the given sequence is a block level
    node, False otherwise.
    """
    return any(isinstance(n, BlockLevelNode) for n in contents)

def join_smart(nodes, **kw):
    """
    Join a sequence of block level and/or inline nodes into a single string.
    """
    if is_block_level(nodes):
        return join_blocks(nodes, **kw)
    else:
        return join_inline(nodes, **kw)

def join_blocks(nodes, **kw):
    """
    Join a sequence of block level nodes into a single string.
    """
    output = []
    for node in nodes:
        if isinstance(node, InlineNode):
            # Without this 'hack' whitespace compaction & line wrapping would
            # not be applied to inline nodes which are direct children of list
            # items that also have children which are block level nodes.
            output.append(join_inline([node], **kw))
        else:
            output.extend(node.render(**kw))
    return output

def join_inline(nodes, **kw):
    """
    Join a sequence of inline nodes into a single string.
    """
    prefix = ' ' * kw['indent']
    rendered_nodes = [n.render(**kw) for n in nodes]
    return "\n".join(textwrap.wrap(compact("".join(rendered_nodes)),
                                   initial_indent=prefix,
                                   subsequent_indent=prefix,
                                   width=TEXT_WIDTH - len(prefix)))

def compact(text):
    """
    Compact whitespace in a string (also trims whitespace from the sides).
    """
    return " ".join(text.split())

def flatten(l):
    """
    From http://stackoverflow.com/a/2158532/788200.
    """
    for el in l:
        if isinstance(el, collections.Iterable) and not isinstance(el, basestring):
            for sub in flatten(el):
                yield sub
        else:
            yield el

if __name__ == '__main__':
    main()

# vim: ft=python ts=4 sw=4 et
