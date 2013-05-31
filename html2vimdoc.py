#!/usr/bin/env python

# Missing features:
# TODO Find tag references in text and mark them.
# TODO Support for <table> elements.
#
# Finding the right abstractions:
# FIXME Quirky mix of classes and functions?
# FIXME The OutputDelimiter stuff is a bit crazy, but I kind of need it? Complexity :-(

"""
html2vimdoc [OPTIONS] [LOCATION]

Convert HTML (and Markdown) documents to Vim help files. When LOCATION is given
it is assumed to be the filename or URL of the input, if --url is given that
URL will be used, otherwise the script reads from standard input. The generated
Vim help file is written to standard output.

Valid options:

  -f, --file=NAME  name of generated help file (embedded
                   in Vim help file as first defined tag)
  -t, --title=STR  title of generated help file
  -u, --url=ADDR   URL of document (to detect relative links)
  -x, --ext=NAME   enable the named Markdown extension
                   (only relevant when input is Markdown)
  -p, --preview    preview generated Vim help file in Vim
  -v, --verbose    make more noise (a lot of noise)
  -h, --help       show this message and exit

This program tries to produce reasonable output given only an HTML or Markdown
document as input, but you can change most defaults with the command line
options listed above.

There are several dependencies that need to be installed to run this program.
The easiest way to install them is in a Python virtual environment:

  # Create the virtual environment.
  virtualenv html2vimdoc

  # Install the dependencies.
  html2vimdoc/bin/pip install beautifulsoup coloredlogs

  # Run the program.
  html2vimdoc/bin/python ./html2vimdoc.py --help

"""

# Standard library modules.
import collections
import getopt
import logging
import os
import re
import sys
import textwrap
import urllib
import urlparse

# External dependency, install with:
#   sudo apt-get install python-beautifulsoup
#   pip install beautifulsoup
from BeautifulSoup import BeautifulSoup, NavigableString, UnicodeDammit

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
logger.setLevel(logging.INFO)
logger.addHandler(coloredlogs.ColoredStreamHandler())

# Mapping of HTML element names to custom Node types.
name_to_type_mapping = {}

def main():
    """
    Command line interface for html2vimdoc.
    """
    filename, title, url, arguments, preview, markdown_extensions = parse_args(sys.argv[1:])
    filename, url, text = get_input(filename, url, arguments, markdown_extensions)
    vimdoc = html2vimdoc(text, title=title, filename=filename, url=url)
    output = vimdoc.encode('utf-8')
    logger.info("Done!")
    if preview:
        os.popen("gvim -c 'set nomod' -", 'w').write(output)
    else:
        print output

def parse_args(argv):
    """
    Parse the command line arguments given to html2vimdoc.
    """
    preview = False
    markdown_extensions = []
    filename = ''
    title = ''
    url = ''
    try:
        options, arguments = getopt.getopt(argv, 'f:t:u:x:pvh', ['file=',
            'title=', 'url=', 'ext=', 'preview', 'verbose', 'help'])
    except getopt.GetoptError, err:
        print str(err)
        print __doc__.strip()
        sys.exit(1)
    for option, value in options:
        if option in ('-f', '--file'):
            filename = value
        elif option in ('-t', '--title'):
            title = value
        elif option in ('-u', '--url'):
            url = value
        elif option in ('-x', '--ext'):
            markdown_extensions.append(value)
        elif option in ('-p', '--preview'):
            preview = True
        elif option in ('-v', '--verbose'):
            logger.setLevel(logging.DEBUG)
        elif option in ('-h', '--help'):
            print __doc__.strip()
            sys.exit(0)
        else:
            assert False, "Unknown option"
    return filename, title, url, arguments, preview, markdown_extensions

def get_input(filename, url, args, markdown_extensions):
    """
    Get text to be converted from standard input, path name or URL.
    """
    source = ''
    if not url and not args:
        logger.info("Reading HTML from standard input ..")
        text = sys.stdin.read()
    else:
        source = args[0] if args else url
        logger.info("Reading input from %s ..", source)
        handle = urllib.urlopen(source)
        text = handle.read()
        handle.close()
        if '://' in source and not url:
            # Positional argument was used with same meaning as --url.
            url = source
        if not filename:
            # Generate embedded filename from base name of input document.
            filename = os.path.basename(source)
            filename = os.path.splitext(filename)[0] + '.txt'
    if source.lower().endswith(('.md', '.mkd', '.mkdn', '.mdown', '.markdown')):
        text = markdown_to_html(text, markdown_extensions)
    return filename, url, text

def markdown_to_html(text, markdown_extensions):
    """
    When the input is Markdown, convert it to HTML so we can parse that.
    """
    logger.info("Converting Markdown to HTML using extensions: %s.", ", ".join(sorted(markdown_extensions)))
    # We import the markdown module here so that the markdown module is not
    # required to use html2vimdoc when the input is HTML.
    from markdown import markdown
    # The Python Markdown module only accepts Unicode and ASCII strings, but we
    # don't know what the encoding of the Markdown text is. BeautifulSoup comes
    # to the rescue with the aptly named UnicodeDammit class :-).
    return markdown(UnicodeDammit(text).unicode, extensions=markdown_extensions)

def html2vimdoc(html, title='', filename='', url='', content_selector='#content', selectors_to_ignore=[], modeline='vim: ft=help'):
    """
    Convert HTML documents to the Vim help file format.
    """
    logger.info("Parsing HTML ..")
    html = decode_hexadecimal_entities(html)
    tree = BeautifulSoup(html, convertEntities=BeautifulSoup.ALL_ENTITIES)
    logger.info("Transforming contents ..")
    title = select_title(tree, title)
    ignore_given_selectors(tree, selectors_to_ignore)
    root = find_root_node(tree, content_selector)
    simple_tree = simplify_node(root)
    make_parents_explicit(simple_tree)
    shift_headings(simple_tree)
    find_references(simple_tree, url)
    # Add an "Introduction" heading to separate the table of contents from the
    # start of the document text.
    simple_tree.contents.insert(0, Heading(level=1, contents=[Text(contents=["Introduction"])]))
    tag_headings(simple_tree, filename)
    logger.info("Generating table of contents ..")
    generate_table_of_contents(simple_tree)
    prune_empty_blocks(simple_tree)
    logger.info("Rendering output ..")
    vimdoc = simple_tree.render(indent=0)
    output = list(flatten(vimdoc))
    logger.debug("Output strings before deduplication: %s", list(unicode(v) for v in output))
    deduplicate_delimiters(output)
    logger.debug("Output strings after deduplication: %s", list(unicode(v) for v in output))
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
    """
    If the caller didn't specify a help file title, we'll try to extract it
    from the HTML <title> or the first <h1> element. Regardless, we'll remove
    the first <h1> element because it's usually the page title (other headings
    are nested below it so the table of contents becomes a bit awkward :-).
    """
    # Improvise a document title?
    if not title:
        elements = tree.findAll(('title', 'h1'))
        if elements:
            title = ''.join(elements[0].findAll(text=True))
    # Remove the first top level heading from the tree.
    headings = tree.findAll('h1')
    if headings:
        headings[0].extract()
    return title

def deduplicate_delimiters(output):
    """
    Deduplicate redundant block delimiters from the rendered Vim help text.
    """
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

def simplify_node(html_node):
    """
    Recursive function to simplify parse trees generated by BeautifulSoup into
    something we can more easily convert into HTML.
    """
    # First we'll get text nodes out of the way since they're very common.
    if isinstance(html_node, NavigableString):
        text = html_node.string
        internal_node = Text(contents=[text])
        logger.debug("Mapping text %r -> %r", text, internal_node)
        return internal_node
    # Now we deal with all of the known & supported HTML elements.
    name = getattr(html_node, 'name', None)
    if name in name_to_type_mapping:
        mapped_type = name_to_type_mapping[name]
        internal_node = mapped_type.parse(html_node)
        logger.debug("Mapping HTML element <%s> -> %r", name, internal_node)
        return internal_node
    # Finally we improvise, trying not to lose information.
    internal_node = simplify_children(html_node)
    logger.debug("Not a supported element! Improvising to preserve content.")
    return internal_node

def simplify_children(node):
    """
    Simplify the child nodes of the given node taken from a parse tree
    generated by BeautifulSoup.
    """
    contents = []
    for child in getattr(node, 'contents', []):
        contents.append(simplify_node(child))
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

def tag_headings(root, filename):
    """
    Generate Vim help file tags for headings.
    """
    tagged_headings = {}
    # Use base name of filename of help file as prefix (scope) for tags.
    prefix = re.sub(r'\.txt$', '', filename)
    logger.debug("Vim help file name without file extension: %r", prefix)
    # If the base name ends in a version number, we'll strip it.
    prefix = re.sub(r'-\d+(\.\d+)*$', '', prefix)
    logger.debug("Tagging headings using prefix %r ..", prefix)
    for node in walk_tree(root, Heading):
        logger.debug("Selecting tag for heading: %s", node)
        tag = node.tag_heading(tagged_headings, prefix)
        if tag:
            logger.debug("Found suitable tag: %s", tag)
            tagged_headings[tag] = node

def find_references(root, url):
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
    logger.debug("Scanning parse tree for hyper links and other references ..")
    for node in walk_tree(root, (HyperLink, Image)):
        if isinstance(node, Image):
            target = node.src
        else:
            target = node.target
        if not target:
            continue
        if target == 'http://www.vim.org/':
            # Don't add a reference to the Vim homepage in Vim help files.
            continue
        if target.startswith('http://vimdoc.sourceforge.net/htmldoc/'):
            # Don't add a reference to the online Vim documentation.
            continue
        # Try to convert relative URLs into absolute URLs.
        if url and not re.match(r'^\w+:', target):
            target = urlparse.urljoin(url, target)
        # Now try to convert absolute URLs into relative URLs... This does
        # actually make sense, but it sure sounds stupid :-p. All it really
        # does is normalize URLs to a common format.
        relative_target = target
        if url:
            relative_target = os.path.relpath(target, url)
        if relative_target.startswith('#'):
            # Skip links to page anchors on the same page.
            continue
        # Exclude literal URLs from list of references.
        if target.replace('mailto:', '') == node.render(indent=0):
            continue
        # Make sure we don't duplicate references.
        if target in by_target:
            r = by_target[target]
        else:
            number = len(by_reference) + 1
            logger.debug("Extracting reference #%i to %s ..", number, target)
            r = Reference(number=number, target=target)
            by_reference.append(r)
            by_target[target] = r
        node.reference = r
    logger.debug("Found %i references.", len(by_reference))
    if by_reference:
        logger.debug("Generating 'References' section ..")
        root.contents.append(Heading(level=1, contents=[Text(contents=["References"])]))
        root.contents.extend(by_reference)

def generate_table_of_contents(root):
    """
    Generate a table of contents for the Vim help file based on the headings
    defined in the Markdown or HTML document provided by the user.
    """
    entries = []
    counters = []
    for heading in walk_tree(root, Heading):
        logger.debug("Stack of counters before reset: %s", counters)
        # Forget no longer relevant counters.
        counters = counters[:heading.level]
        logger.debug("Stack of counters after reset: %s", counters)
        # Make the stack of counters big enough.
        while len(counters) < heading.level:
            counters.append(1)
        logger.debug("Stack of counters after padding: %s", counters)
        entries.append(TableOfContentsEntry(
            number=counters[heading.level - 1],
            text=compact(join_inline(heading.contents, indent=heading.level)),
            indent=heading.level,
            tag=getattr(heading, 'tag', None)))
        counters[heading.level - 1] += 1
    logger.debug("Table of contents: %s", entries)
    root.contents.insert(0, Heading(level=1, contents=[Text(contents=["Contents"])]))
    root.contents.insert(1, BlockLevelSequence(contents=entries))

def prune_empty_blocks(root):
    """
    Prune empty block level nodes from the tree.
    """
    def recurse(node):
        if hasattr(node, 'contents'):
            filtered_children = []
            for child in node.contents:
                recurse(child)
                if child:
                    filtered_children.append(child)

            node.contents = filtered_children
    recurse(root)

def make_parents_explicit(root):
    """
    Add links from child nodes to parent nodes.
    """
    def recurse(node, parent):
        if isinstance(node, Node):
            node.parent = parent
            for child in getattr(node, 'contents', []):
                recurse(child, node)
    recurse(root, None)

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

    """
    Trivial class to encapsulate output text (delimiters between the rendered
    text of block level nodes) with a bit of state (to distinguish rendered
    text from delimiters).

    Note that most of the actual logic for handling of output delimiters is
    currently contained in the function ``deduplicate_delimiters()``.
    """

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
        nodes = [repr(n) for n in getattr(self, 'contents', [])]
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

    @property
    def parents(self):
        """
        Generator that yields all parents of a node.
        """
        node = self
        while node:
            node = node.parent
            yield node

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

    def __nonzero__(self):
        """
        Make it possible to recognize and prune empty block level sequences.
        """
        return any(self.contents)

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

    def tag_heading(self, existing_tags, prefix):
        # Look for a <code> element (indicating a source code
        # entity) whose text has not yet been used as a tag.
        matches = walk_tree(self, CodeFragment)
        logger.debug("Found %i code fragments inside heading: %s", len(matches), matches)
        for node in matches:
            tag = create_tag(node.text, prefix=prefix, is_code=True)
            logger.debug("Checking if %r (from %r) can be used as a tag ..", tag, node.text)
            if tag not in existing_tags:
                # Found a usable tag.
                self.tag = tag
                return tag
        # Fall back to a tag generated from the heading's text.
        text = join_inline(self.contents, indent=0)
        tag = create_tag(text, prefix=prefix, is_code=False)
        logger.debug("Checking if %r (from %r) can be used as a tag ..", tag, text)
        if tag not in existing_tags:
            self.tag = tag
            return tag

    def render(self, **kw):
        logger.debug("Rendering heading: %s", self)
        # We start with a line containing the marker symbol for headings,
        # repeated on the full line. The symbol depends on the level.
        lines = [('=' if self.level == 1 else '-') * TEXT_WIDTH]
        # Render the heading's text.
        text = join_inline(self.contents, **kw)
        suffix = ' ~'
        # Add a section tag?
        if hasattr(self, 'tag'):
            tag = "*%s*" % self.tag
            if self.tag in text:
                # If the heading references the tag literally, we'll just use
                # that (instead of having to add a redundant tag).
                text = text.replace(self.tag, tag)
                # References to tags are actually invalid inside proper
                # headings, but since we also added the marker line at the top
                # of the heading, we can leave off the "~" symbol and forgo the
                # additional highlighting.
                suffix = ''
            else:
                # If we can't reference the tag literally, we'll add the
                # section tag on the second line, aligned to the right.
                prefix = ' ' * (TEXT_WIDTH - len(tag))
                lines.append(prefix + tag)
        # Prepare the prefix & suffix for each line, hard wrap the
        # heading text and apply the prefix & suffix to each line.
        prefix = ' ' * kw['indent']
        width = TEXT_WIDTH - len(prefix) - len(suffix)
        lines.extend(prefix + l + suffix for l in textwrap.wrap(text, width=width))
        return [self.start_delimiter, "\n".join(lines), self.end_delimiter]

@html_element('p')
class Paragraph(BlockLevelNode):

    """
    Block level node to represent paragraphs of text.
    Maps to the HTML element ``<p>``.
    """

    def render(self, **kw):
        # If the paragraph contains only an image (possible wrapped in another
        # element) the paragraph is indented by a minimum of two spaces.
        if len(self.contents) == 1 and len(walk_tree(self, Image)) == 1:
            kw['indent'] = max(2, kw['indent'])
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
        return PreformattedText(contents=["\n".join(lines)])

    def render(self, **kw):
        prefix = ' ' * max(kw['indent'], 2)
        lines = self.contents[0].splitlines()
        text = "\n".join(prefix + line for line in lines)
        return [self.start_delimiter, text, self.end_delimiter]

@html_element('ul', 'ol')
class List(BlockLevelNode):

    """
    Block level node to represent ordered and unordered lists.
    Maps to the HTML elements ``<ol>`` and ``<ul>``.
    """

    @staticmethod
    def parse(html_node):
        return List(ordered=(html_node.name=='ol'),
                    contents=simplify_children(html_node))

    def render(self, **kw):
        # First pass: Render the child nodes and pick the right delimiter.
        items = []
        delimiter = OutputDelimiter('\n')
        num_lines = 0
        for node in self.contents:
            if isinstance(node, ListItem):
                text = node.render(number=len(items) + 1, **kw)
                items.append(text)
                for x in text:
                    if isinstance(x, basestring):
                        num_lines += x.count('\n')
                num_lines += 1
        logger.debug("num_lines=%i, #items=%i, ratio=%.2f", num_lines, len(items), num_lines / float(len(items)))
        if (num_lines / float(len(items))) > 1.5:
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
        # Prefix the list item bullet and return the result.
        # XXX We explicitly *don't* add any output delimiters here, because
        # they will be chosen *after* all of the list items have been rendered.
        return [prefix] + text

# TODO Parse and render tabular data.
#@html_element('table')

class Table(BlockLevelNode):

    """
    Block level node to represent tabular data.
    Maps to the HTML element ``<table>``.
    """

    def render(self, **kw):
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

class TableOfContentsEntry(BlockLevelNode):

    """
    Block level node to represent a line in the table of contents.
    """

    start_delimiter = OutputDelimiter('\n')
    end_delimiter = OutputDelimiter('\n')

    def __repr__(self):
        return "TableOfContentsEntry(number=%i, text=%r, indent=%i)" % (self.number, self.text, self.indent)

    def render(self, **kw):
        text = ''
        # Render the indentation.
        text += " " * self.indent
        # Render the counter.
        text += "%i. " % self.number
        # Render the text.
        text += self.text
        if self.tag:
            tag = "|%s|" % self.tag
            # Render the padding.
            padding = max(1, TEXT_WIDTH - len(text) - len(tag))
            text += " " * padding
            # Render the tag.
            text += tag
        return [self.start_delimiter, text, self.end_delimiter]

class InlineSequence(InlineNode):

    """
    Inline node to represent a sequence of one or more inline nodes.
    """

    def __nonzero__(self):
        """
        Make it possible to recognize and prune empty inline sequences.
        """
        return any(self.contents)

    def __len__(self):
        """
        Needed by HyperLink.render().
        """
        return len(self.contents)

    def render(self, **kw):
        return join_inline(self.contents, **kw)

@html_element('img')
class Image(InlineNode):

    """
    Inline node to represent images.
    Maps to the HTML element ``<img>``.
    """

    @staticmethod
    def parse(html_node):
        return Image(src=html_node.get('src', ''),
                     alt=html_node.get('alt', ''))

    def __nonzero__(self):
        return bool(self.src or self.alt)

    def __repr__(self):
        return "Image(src=%r, alt=%r)" % (self.src, self.alt)

    def render(self, **kw):
        if hasattr(self, 'reference'):
            text = "%s (see reference [%i])" % (self.alt, self.reference.number)
        else:
            text = self.alt or '(unlabeled image)'
        return "Image: " + text

@html_element('a')
class HyperLink(InlineNode):

    """
    Inline node to represent hyper links.
    Maps to the HTML element ``<a>``.
    """

    @staticmethod
    def parse(html_node):
        return HyperLink(target=html_node.get('href', ''),
                         contents=simplify_children(html_node))

    def __repr__(self):
        text = self.render(indent=0)
        return "HyperLink(text=%r, target=%r, reference=%r)" % (text, self.target, getattr(self, 'reference', None))

    def render(self, **kw):
        images = walk_tree(self, Image)
        if len(self.contents) == 1 and len(images) == 1:
            # If the hyper link contains a single child node which is
            # (or contains) an image, we add a reference for the hyper
            # link but not the image.
            raw_text = "Image: " + images[0].alt
            text = join_inline([Text(contents=[raw_text])], **kw)
        else:
            text = join_inline(self.contents, **kw)
        # Turn links to Vim documentation into *tags*.
        if self.target.startswith('http://vimdoc.sourceforge.net/htmldoc/'):
            tag = urlparse.urlparse(self.target).fragment
            # Tags are not valid inside headings, so we have to check.
            if tag and not any(isinstance(n, Heading) for n in self.parents):
                tag = urllib.unquote(tag)
                if text.find(tag) >= 0:
                    text = text.replace(tag, '|%s|' % tag)
                else:
                    text = '%s (see |%s|)' % (text, tag)
        # Add references as needed.
        if hasattr(self, 'reference'):
            text = "%s [%i]" % (text, self.reference.number)
        return text

@html_element('code', 'tt')
class CodeFragment(InlineNode):

    """
    Inline node to represent code fragments.
    Maps to the HTML elements ``<code>`` and ``<tt>``.
    """

    @staticmethod
    def parse(html_node):
        return CodeFragment(text=''.join(html_node.findAll(text=True)))

    def __repr__(self):
        return "CodeFragment(text=%r)" % self.text

    def render(self, **kw):
        # $VIMRUNTIME/syntax/help.vim doesn't actually define very rich
        # highlighting: We can use `back ticks` to highlight code fragments,
        # but only when the code fragment doesn't contain spaces... Also, this
        # doesn't work in headings. To still make the transition between
        # regular text and code fragments visible to the user, we'll improvise
        # with single or double quotes.
        if re.match('^[` \t\r\n]+$', self.text) and not any(isinstance(n, Heading) for n in self.parents):
            return self.text
        elif self.text.find("'") >= 0:
            return '"%s"' % self.text
        else:
            return "'%s'" % self.text

@html_element('i', 'em')
class Emphasis(InlineNode):

    """
    Inline node to represent emphasis.
    Maps to the HTML elements ``<i>`` and ``<em>``.
    """

    @staticmethod
    def parse(html_node):
        return Emphasis(contents=simplify_children(html_node))

    def __repr__(self):
        return "Emphasis(contents=%r)" % self.contents

    def render(self, **kw):
        return "_%s_" % join_inline(self.contents, **kw)

@html_element('b', 'strong')
class Strong(InlineNode):

    """
    Inline node to represent strong / bold font.
    Maps to the HTML elements ``<b>`` and ``<strong>``.
    """

    @staticmethod
    def parse(html_node):
        return Strong(contents=simplify_children(html_node))

    def __repr__(self):
        return "Strong(contents=%r)" % self.contents

    def render(self, **kw):
        # We use **double** asterisks because a word enclosed in *single*
        # asterisks already has a meaning: It's a help tag definition.
        return "**%s**" % join_inline(self.contents, **kw)

class Text(InlineNode):

    """
    Inline node to represent a sequence of text.
    """

    def __nonzero__(self):
        """
        Make it possible to recognize and prune empty text nodes.
        """
        text = self.contents[0]
        return text and not text.isspace()

    def render(self, **kw):
        return self.contents[0]

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
            # items that also have children which are block level nodes (that
            # was a mouthful).
            output.append(join_inline([node], **kw))
        else:
            output.extend(node.render(**kw))
    return output

def join_inline(nodes, **kw):
    """
    Join a sequence of inline nodes into a single string.
    """
    # Render the indentation at the current level.
    prefix = ' ' * kw['indent']
    # Reset the indentation for nested inline nodes.
    kw['indent'] = 0
    # Render the inline nodes.
    logger.debug("Inline nodes: %s", nodes)
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

def create_tag(text, prefix, is_code):
    """
    Convert arbitrary text to a Vim help file tag.
    """
    if is_code:
        # Preserve the case of programming language identifiers.
        anchor = text
        # Replace operators with words so we don't lose too much information.
        for op, word in (('+', 'add'), ('-', 'sub'), ('*', 'mul'), ('/', 'div')):
            anchor = anchor.replace(op, ' %s ' % word)
        # Replace parenthesized expressions with just the parentheses
        # (intent: to not include function arguments in tags).
        anchor = re.sub(r'\s*\(.*?\)', '()', anchor)
    else:
        # Lowercase regular English expressions.
        anchor = text.lower()
        # Remove parenthesized expressions.
        anchor = re.sub(r'\(.*?\)', '', anchor)
        # Remove apostrophes (replacing them with dashes is silly).
        anchor = re.sub(r"(\w)'(\w)", r'\1\2', anchor)
        # Remove "insignificant" colons.
        anchor = re.sub(r':\s+', ' ', anchor)
        # Remove fluff words.
        tokens = []
        for token in anchor.split():
            if token not in ('a', 'the', 'and', 'some'):
                tokens.append(token)
        anchor = " ".join(tokens)
    # Apply the prefix only when it's not completely redundant.
    if not is_code and not prefix.lower() in anchor.lower():
        anchor = prefix + '-' + anchor
    # Tags can only contain a limited set of characters.
    if is_code:
        anchor = re.sub('[^A-Za-z0-9_().:]+', '-', anchor)
    else:
        anchor = re.sub('[^A-Za-z0-9_().]+', '-', anchor)
    # Trim leading/trailing sanitized characters.
    return anchor.strip('-')

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
