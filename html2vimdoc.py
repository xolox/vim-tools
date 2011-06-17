#!/usr/bin/env python

"""
Convert HTML documents to Vim help files.

Author: Peter Odding <peter@peterodding.com>
Last Change: June 17, 2011
Homepage: http://github.com/xolox/vim-tools
License: MIT

The Python script "html2vimdoc" converts HTML documents to Vim's plain text
help file format. Help tags are generated for headings so that you can quickly
jump to any section of the generated documentation. The Beautiful Soup HTML
parser is used so that even malformed HTML can be converted. When given
Markdown input it will be automatically converted to HTML using the Python
Markdown module.

On Debian/Ubuntu you can install the Python modules that are used in this
script by executing the following command in a terminal:

  sudo apt-get install python-beautifulsoup python-markdown

To-do list:
 - Refactor code to be more logical
 - Automatic hyper links in paragraphs
 - Compact small lists, expand large ones
"""

usage = """
html2vimdoc [OPTIONS] [LOCATION]

Convert HTML documents to Vim help files. When LOCATION is
given it is assumed to be the filename or URL of the input,
if --url is given that URL will be used, otherwise the
script reads from standard input. The generated Vim help
file is written to standard output.

Valid options:

  -h, --help       show this message and exit
  -f, --file=NAME  name of generated help file (embedded
                   in Vim help file as first defined tag)
  -t, --title=STR  title of the generated help file
  -u, --url=ADDR   URL of document (to detect relative links)
"""

# Standard library modules.
import getopt
import os
import re
import sys
from textwrap import dedent
import urllib

# Extra dependencies.
from BeautifulSoup import BeautifulSoup, Comment

def main():
  filename, title, url, arguments = parse_args(sys.argv[1:])
  filename, url, text = get_input(filename, url, arguments)
  html = markdown_to_html(text)
  print html2vimdoc(html, filename=filename, title=title, url=url)

def html2vimdoc(html, filename='', title='', url=''):
  """ This function performs the conversion from HTML to Vim help file. """
  title, firstlevel, tree, refs = parse_html(html, title, url)
  blocks = simplify_tree(tree, [])
  output = []
  if filename or title:
    line = []
    if filename:
      line.append('*' + filename + '*')
    if title:
      line.append(title)
    output.append('  '.join(line))
  basename = os.path.splitext(filename)[0]
  parts = basename.split('-')
  if len(parts) == 2 and re.match(r'^\d+(\.\d+)*$', parts[1]):
    basename = parts[0]
  tags = []
  for item in blocks:
    print_block(item, output, tags, firstlevel, basename)
  if refs:
    print_heading('References', output, tags, '=', basename)
    refs = [(refnum, url) for url, refnum in refs.iteritems()]
    lines = []
    for refnum, url in sorted(refs):
      lines.append('[%i] %s' % (refnum, url))
    output.append('\n'.join(lines))
  output.append('vim: ft=help')
  text = '\n\n'.join(output)
  for tag in tags:
    pattern = "([^|])'(%s)'([^|])" % tag
    text = re.sub(pattern, r'\1|\2|\3', text)
  return text

def parse_args(argv):
  """ Parse command line arguments given to html2vimdoc. """
  filename, title, url = '', '', ''
  try:
    options, arguments = getopt.getopt(argv, 'hf:t:u:', ['file=', 'title=', 'help', ])
  except getopt.GetoptError, err:
    print str(err)
    print usage.strip()
    sys.exit(1)
  for option, value in options:
    if option in ('-h', '--help'):
      print usage.strip()
      sys.exit(0)
    elif option in ('-f', '--file'):
      filename = value
    elif option in ('-t', '--title'):
      title = value
    elif option in ('-u', '--url'):
      url = value
    else:
      assert False, "Unknown option"
  return filename, title, url, arguments

def get_input(filename, url, args):
  """ Get text to be converted from standard input, path name or URL. """
  if not url and not args:
    text = sys.stdin.read()
  else:
    location = args and args[0] or url
    if not filename:
      # Generate embedded filename from base name of input document.
      filename = os.path.splitext(os.path.basename(location))[0] + '.txt'
    if not url and '://' in location:
      # Positional argument was used with same meaning as --url.
      url = location
    handle = urllib.urlopen(location)
    text = handle.read()
    handle.close()
  return filename, url, text

def markdown_to_html(text):
  """ When input looks like Markdown, convert to HTML so we can parse that. """
  if text.startswith('#'):
    try:
      # Workaround for "UnicodeDecodeError: Markdown only accepts Unicode or ASCII input".
      text = text.decode('utf-8')
    except:
      pass
    from markdown import markdown
    text = markdown(text)
  return text

def parse_html(contents, title, url):
  """ Parse HTML input using Beautiful Soup parser. """
  # Decode hexadecimal entities because Beautiful Soup doesn't support them :-\
  contents = re.sub(r'&#x([0-9A-Fa-f]+);', lambda n: chr(int(n.group(1), 16)), contents)
  # Remove copyright signs.
  contents = contents.replace(u'\xa9', 'Copyright')
  tree = BeautifulSoup(contents, convertEntities = BeautifulSoup.ALL_ENTITIES)
  # Restrict conversion to content text.
  root = tree.find(id = 'content')
  if not root:
    try:
      root = tree.html.body
    except:
      # Don't break when html.body doesn't exist.
      root = tree
  # Count top level headings, find help file title.
  headings = root.findAll('h1')
  if headings:
    if not title:
      title = compact(node_text(headings[0]))
      # Remove heading from parse tree.
      headings[0].extract()
  # Remove HTML comments from parse tree.
  [c.extract() for c in root.findAll(text = lambda n: isinstance(n, Comment))]
  # XXX Hacks for the Lua/APR binding documentation: Remove <a href=..>#</a>
  # and <span>test coverage: xx%</span> elements from headings.
  [n.extract() for n in root.findAll('a') if node_text(n) == '#']
  [n.extract() for n in root.findAll('span') if 'test coverage' in node_text(n)]
  # Transform <code> fragments into 'single quoted strings'.
  def quote(node):
    text = node_text(node)
    if text.startswith("'") and text.endswith("'"):
      return text
    else:
      return "'%s'" % text
  [n.replaceWith(quote(n)) for n in root.findAll('code') if n.parent.name != 'pre']
  # Transform hyper links and images into textual references.
  refs = {}
  for node in root.findAll(('a', 'img')):
    if node.name == 'img':
      img_refnum = len(refs) + 1
      refs[node['src']] = img_refnum
      node.insert(len(node), u'    %s, see reference [%i]' % (node['alt'] or 'Image', img_refnum))
    else:
      link_target = node['href']
      link_text = node_text(node)
      # XXX print >>sys.stderr, link_target
      # Try to transform relative into absolute links.
      if url and not re.match(r'^\w+:', link_target):
        link_target = os.path.join(url, link_target)
      if (url and os.path.relpath(link_target, url) or link_target).startswith('#'):
        # Skip links to page anchors on the same page.
        continue
      elif link_target == 'http://www.vim.org/':
        # Don't add a reference to the Vim homepage in Vim help files.
        continue
      elif link_target.startswith('http://vimdoc.sourceforge.net/htmldoc/'):
        # Turn links to Vim documentation into *tags* without reference.
        try:
          anchor = urllib.unquote(link_target.split('#')[1])
          if anchor and link_text.find(anchor) >= 0:
            node.replaceWith(link_text.replace(anchor, '|%s|' % anchor))
          else:
            node.replaceWith('%s (see |%s|)' % (link_text, anchor))
          continue
        except:
          pass
      # Exclude relative URLs and literal URLs from list of references.
      if '://' in link_target and link_target != link_text:
        link_target = urllib.unquote(link_target)
        if link_target in refs:
          link_refnum = refs[link_target]
        else:
          link_refnum = len(refs) + 1
          refs[link_target] = link_refnum
        node.insert(len(node), u' [%i]' % link_refnum)
  # Simplify parse tree into list of headings/paragraphs/blocks.
  return title, len(headings) == 1 and 2 or 1, root, refs

def simplify_tree(node, output, para_id=0):
  """ Convert the parse tree generated by Beautiful Soup into a list of block elements. """
  name = getattr(node, 'name', None)
  if name == 'p':
    # Update current paragraph identity.
    para_id = id(node)
  if name in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
    output.append((name, node_text(node)))
  elif name == 'pre':
    text = node_text(node)
    text = trim_lines(text.rstrip())
    output.append((name, dedent(text)))
  elif name == 'table':
    rows = []
    for row in node.findAll('tr'):
      columns = []
      for column in row.findAll({ 'th': True, 'td': True }):
        columns.append(compact(node_text(column)))
      rows.append(columns)
    output.append((name, rows))
  elif name in ('li', 'dt', 'dd'):
    output.append((name, compact(node_text(node))))
  elif not isinstance(node, unicode):
    for child in node:
      simplify_tree(child, output, para_id)
  else:
    text = compact(node)
    if text:
      if output:
        lastitem = output[len(output) - 1]
        if lastitem[1] == para_id:
          newitem = ('text', para_id, lastitem[2] + node)
          output[len(output) - 1] = newitem
          return output
      output.append(('text', para_id, node))
  return output

def print_block(item, output, tags, level, filename):
  """ Convert a single block to the Vim help file format. """
  # Headings.
  if item[0] == 'h1':
    print_heading(item[1], output, tags, '=', filename)
  elif item[0] == 'h2':
    print_heading(item[1], output, tags, level == 2 and '=' or '-', filename)
  elif item[0] in ('h3', 'h4', 'h5', 'h6'):
    print_heading(item[1], output, tags, '-', filename)
  elif item[0] == 'pre':
    # Join the previous and current block because the '>' marker is hidden
    # and can visually be considered an empty line.
    prevblock = output[len(output)-1].rstrip()
    thisblock = '    ' + item[1].replace('\n', '\n' + '    ')
    output[len(output)-1] = prevblock + '\n>\n' + thisblock
  elif item[0] == 'table':
    output.append(wrap_table(item[1]))
  else:
    text = item[item[0] == 'text' and 2 or 1]
    text = trim_lines(text)
    if item[0] in ('li', 'dt', 'dd'):
      text = ' - ' + text
    # Make the Lua reference manual more useful.
    text = re.sub(u'\xa7(\\d+(\\.\\d+)*)', '|lua-\\1|', text)
    text = wrap_text(text)
    output.append(text)

def print_heading(text, output, tags, marker, filename):
  """ Convert a heading (of any level) to the Vim help file format. """
  heading = compact(text)
  anchor = ''
  # Try to find a unique anchor indicated in the source HTML with
  # <code> and in the format we have here with 'single-quotes'.
  m = re.search(r"'(\S+)'", text)
  anchor = m and m.group(1)
  if anchor and anchor not in tags:
    heading = heading.replace("'%s'" % anchor, '*%s*' % anchor)
    output.append(marker * 79 + '\n' + heading)
    tags.append(anchor)
  else:
    # We didn't find a unique anchor, make something up ;-)
    if len(text.split()) < 6:
      anchor = re.sub('[^a-z0-9_().:]+', '-', heading.lower())
      anchor = re.sub('^the-', '', anchor)
      anchor = re.sub('-the-', '-', anchor)
      anchor = anchor.strip('-')
      if filename:
        filename = filename.lower()
        if filename not in anchor:
          anchor = filename + '-' + anchor
      if anchor in tags:
        # Never generate duplicate tags!
        anchor = ''
      else:
        tags.append(anchor)
    output.append(
        marker * 79 + '\n'
      + (('%080s\n' % ('*' + anchor + '*')) if anchor else '')
      + heading + ' ~')

def wrap_text(text, width=78, startofline=''):
  """ Re-flow paragraph by adding hard line breaks. """
  lines = []
  cline = startofline
  indent = re.match(r'^\s*', text).group(0)
  for word in text.split():
    wordlen = len(word.replace('|', ''))
    test = len(cline.replace('|', '')) + wordlen + 1
    if test <= width or wordlen >= width / 3 and len(cline) < (width / 0.8) and test < (width * 1.2):
      delimiter = re.match('[.?!]$', cline) != None and word[0].isupper() and '  ' or ' '
      cline = len(cline) != 0 and (cline + delimiter + word) or word
    else:
      lines.append(cline)
      # Indent continuation lines of wrapped list items.
      if cline.startswith('- ') or cline.startswith('   '):
        cline = '   ' + word
      else:
        cline = startofline + word
  if len(cline) > 0:
    lines.append(cline)
  return indent + '\n'.join(lines)

def wrap_table(rows, width=78, padding='  '):
  """ Generate ASCII table with wrapped columns. """
  numcols = len(rows[0])
  widths = [0] * numcols
  padwidth = numcols * len(padding)
  for columns in rows:
    for colnum, text in enumerate(columns):
      widths[colnum] = max(widths[colnum], len(text))
  remaining_width = width - padwidth
  remaining_columns = numcols
  if sum(widths) + padwidth > width:
    for colnum, colwidth in enumerate(widths):
      widths[colnum] = min(colwidth, remaining_width / remaining_columns)
      remaining_width -= widths[colnum]
      remaining_columns -= 1
    # TODO This can be improved
    #widths = [width / numcols] * numcols
  output = []
  for row in rows:
    columns = []
    # Wrap individual columns.
    for colnum, text in enumerate(row):
      # Wrap text in column.
      lines = []
      line = ''
      for word in text.split():
        if len(line) + len(word) <= widths[colnum]:
          line += (line and ' ' or '') + word
        else:
          lines.append(line)
          line = word
      if line:
        lines.append(line)
      # Left justify, pad columns with spaces.
      for i, line in enumerate(lines):
        lines[i] = line.ljust(widths[colnum])
      columns.append(lines)
    # Combine wrapped columns.
    i = 0
    while i < max(len(column) for column in columns):
      line = []
      for colnum, column in enumerate(columns):
        if i < len(column):
          line.append(column[i])
        else:
          line.append(' ' * widths[colnum])
      output.append('  ' + '  '.join(line))
      i += 1
  output = [line.rstrip() for line in output]
  output[0] += ' ~'
  return '\n'.join(output)

def node_text(node):
  """ Get all text contained by the given parse tree node. """
  text = ''.join(node.findAll(text = True))
  # HACK for Lua/APR binding documentation.
  text = text.replace(u'\u2192', '->')
  return text

def trim_lines(s):
  """ Trim empty, leading lines from the given string. """
  return re.sub('^([ \t]*\n)+', '', s)

def compact(s):
  """ Compact sequences of whitespace into single spaces. """
  return ' '.join(s.split())

if __name__ == '__main__':
  import codecs
  streamWriter = codecs.lookup('utf-8')[-1]
  sys.stdout = streamWriter(sys.stdout)
  main()

# vim: ts=2 sw=2 et
