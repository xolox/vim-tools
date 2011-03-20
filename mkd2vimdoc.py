#!/usr/bin/python

"""
Convert Markdown formatted text to Vim's help file format.

Author: Peter Odding <peter@peterodding.com>
Last Change: March 19, 2011
Homepage: http://github.com/xolox/vim-tools
License: MIT

This Python module converts Markdown formatted text to Vim's help file format.
I created this code because I write a README.md document for every project I
publish on GitHub and thought it would be nice to include these documents in a
more readable format with the ZIP archives I upload to www.vim.org. The code is
basically one big hack, desperately trying to avoid becoming a multi pass
parser but it works and I'm happy with it, so there ;-)
"""

import re, urllib

class mkd2vimdoc:

  TEXT_WIDTH = 78
  TAB_WIDTH = 4
  INDENT = ' ' * TAB_WIDTH
  FANCY_BULLETS = False # disabled because on Windows &encoding = 'latin1' which doesn't support fancy bullets :-(

  # Regexen to match various kinds of text that occur in Markdown documents.
  html_regex = re.compile(r'<([^>]+)>')
  indent_regex = re.compile(r'^(\s*)\S')
  reference_definition_regex = re.compile(r'\n\s*\[(\w+)\]:\s+([^\n]+)')
  reference_definition_regex = re.compile(r'\n\s*\[([A-Za-z0-9_-]+)\]:\s+([^\n]+)')
  linkref_regex = re.compile(r"""
    \[ ( (?: [^\]\\] | \\. )+ ) \]   # link text.
    \s*                              # optional whitespace.
    (?:                              # either of:
     \[ ( (?: [^\]\\] | \\. )+ ) \]  #  - reference to definition.
     |
     \( ( (?: [^)\\] | \\. )+ ) \)   #  - inline target.
    )""", re.VERBOSE)
  quoted_regex = re.compile(r'([`"\'])([^`"\']+)\1')
  whitespace_regex = re.compile(r'\s+')

  def convert(self, text, helpfile=''): # {{{1
    text = text.replace('\r\n', '\n')
    text = text.expandtabs(self.TAB_WIDTH)
    tags = self.find_tags(text)
    self.named_refs = {} # mapping of string(link name) => string(URL)
    self.numbered_refs = {} # mapping of string(URL) => reference number
    text = self.reference_definition_regex.sub(self.extract_named_references, text)
    blocks = text.split('\n\n')
    output = []
    header_tags = {}
    self.convert_heading(output, blocks.pop(0), header_tags, helpfile)
    for i, block in enumerate(blocks):
      if block != '' and not block.isspace():
        #sys.stderr.write("\rConverting block %i .." % i)
        if not (self.convert_heading(output, block, header_tags) or self.convert_codeblock(output, block)):
          output.append('')
          self.convert_block(output, block, tags)
        #sys.stderr.write(output[len(output)-1])
    if self.numbered_refs:
      output.append('\n%s\nReferences ~\n' % ('=' * self.TEXT_WIDTH))
      ordered = [(v, k) for k, v in self.numbered_refs.iteritems()]
      ordered.sort()
      for number, target in ordered:
        output.append('[%i] %s' % (number, target))
    output.append('\nvim: syntax=help nospell')
    #sys.stderr.write("\n")
    return '\n'.join(output)

  def extract_named_references(self, m):
    self.named_refs[m.group(1)] = m.group(2)
    return ''

  def find_tags(self, text): # {{{1
    # This *hack* saves me from having to switch to a multi pass conversion :-)
    tags = []
    for tag in re.findall(r'^##+[^`\n]*`([^`\n]+)`', text, re.MULTILINE):
      tags.append(tag)
    return tags

  def convert_heading(self, output, text, header_tags, helpfile=''): # {{{1
    if not text.startswith('#'):
      return False
    level, x = 1, len(text)
    while level < x and text[level] == '#':
      level += 1
    text = self.html_regex.sub(' ', text[level:])
    text = self.whitespace_regex.sub(' ', text.strip())
    if level == 1:
      output.append('*%s*  %s' % (helpfile, text))
    else:
      output.append('')
      m = self.quoted_regex.search(text)
      text = self.quoted_regex.sub(r'\2', text)
      tag = m and m.group(2)
      if tag and tag not in header_tags:
        text = text.replace(tag, '*%s*' % tag)
        header_tags[tag] = True
      else:
        text += ' ~'
      marker = level == 2 and '=' or '-'
      text = self.linkref_regex.sub(self.linkref_cb, text)
      output.append(marker * self.TEXT_WIDTH + '\n' + text)
    return True

  def convert_codeblock(self, output, block): # {{{1
    if block.startswith(self.INDENT):
      output.append('>')
      output.append(block)
      return True

  def convert_block(self, output, text, tags): # {{{1
    # Replace back ticks with regular quotes.
    def backticks_cb(m):
      t = m.group(0)[1:-1]
      t = t.replace('<', '&lt;')
      t = t.replace('>', '&gt;')
      if re.match(r'^:\w+!?$', t):
        return t
      else:
        return "'%s'" % t
    text = re.sub(r'`[^`]+`', backticks_cb, text)
    # Remove *emphasis* (no equivalent in Vim help format).
    text = re.sub(r'\*\*(\S.*?\S)\*\*', r'\1', text)
    text = re.sub(r'\*(\S.*?\S)\*', r'\1', text)
    # Replace HTML line breaks with Markdown ones (assuming <br> is followed by \n).
    text = text.replace('<br>', '  ')
    # Join hard-wrapped lines where appropriate.
    i, lines = 0, text.splitlines()
    while i < len(lines) - 1:
      m, n = self.indent_regex.match(lines[i]), self.indent_regex.match(lines[i + 1])
      if m and n and m.group(1) == n.group(1) \
              and not lines[i].endswith('  ') \
              and not re.match(r'^\s*\*\s', lines[i + 1]): # don't join bulleted lists
        lines[i] += ' ' + lines[i + 1].rstrip()
        del lines[i + 1]
      else:
        lines[i] = lines[i].rstrip()
        i += 1
    for i, line in enumerate(lines):
      # Convert embedded image into reference?
      image_link = re.match(r'^!\[(.*)\]\((.*)\)$', line)
      if image_link:
        label = image_link.group(1)
        href = image_link.group(2)
        line = '%s[%s, see reference](%s)' % (self.INDENT, label, href)
      line = self.linkref_regex.sub(self.linkref_cb, line)
      # Mark tags in paragraphs.
      for tag in tags:
        e = re.escape(tag)
        # Unquote occurrences of tag.
        line = re.sub("'(%s)'" % e, r'\1', line)
        # Wrap occurrences of tag in |markers|.
        line = re.sub(r'(\s|\b)(%s)(\s|\b)' % e, r'\1|\2|\3', line)
      lines[i] = line
    # Re-wrap the text to the configured line width.
    def strip_html_cb(m):
      t = m.group(1)
      s = t.startswith('http://') or '@' in t
      return s and t or ''
    for i, line in enumerate(lines):
      # Strip embedded HTML elements.
      line = self.html_regex.sub(strip_html_cb, line)
      # Convert HTML entities to plain text.
      line = line.replace('&lt;', '<')
      line = line.replace('&gt;', '>')
      # Unquote Vim-style key sequences.
      line = re.sub(r"'(<[^>]+>)'", r'\1', line)
      line = line.replace('<Control-', '<C-')
      line = line.replace('<Ctrl-', '<C-')
      # Re-indent list items.
      if re.match(r'^\s*\*\s', line):
        # Add fancy list bullets?
        if self.FANCY_BULLETS:
          line = re.sub(r'^\s*\*\s', ' \xe2\x80\xa2 ', line)
        else:
          line = re.sub(r'^\s*\*\s', ' * ', line)
        lines[i] = line
      lines[i] = self.wrap(line, self.TEXT_WIDTH)
    output.append('\n'.join(lines))

  def linkref_cb(self, m): # {{{1
    # Remove Markdown escaping.
    text = re.sub(r'\\(.)', r'\1', m.group(1))
    if m.group(2) != None:
      # named reference
      reference = self.named_refs[m.group(2)]
    else:
      # inline link
      reference = m.group(3)
      # named_refs[reference] = reference
    if reference == 'http://www.vim.org/':
      # Don't add a reference to the Vim homepage in a Vim help document.
      return text
    if reference.startswith('http://vimdoc.sourceforge.net/htmldoc/'):
      # Turn links to Vim documentation into *tags* without reference.
      try:
        anchor = urllib.unquote(reference.split('#')[1])
        if text.find(anchor) >= 0:
          return text.replace(anchor, '|%s|' % anchor)
        else:
          return '%s (see |%s|)' % (text, anchor)
      except:
        pass
    number = self.numbered_refs.get(reference, len(self.numbered_refs) + 1)
    self.numbered_refs[reference] = number
    # TODO text.strip()?
    return '%s [%d]' % (text, number)

  def wrap(self, text, width): # {{{1
    lines = []
    cline = u''
    text = text.replace('\xc2\xa9', 'Copyright')
    text = text.decode('UTF-8')
    indent = re.match(r'^\s*', text).group(0)
    for word in text.split():
      wordlen = len(word.replace(u'|', u''))
      test = len(cline.replace(u'|', u'')) + wordlen + 1
      if test <= width or wordlen >= width / 3 and len(cline) < (width / 0.8) and test < (width * 1.2):
        delimiter = re.match('[.?!]$', cline) != None and word[0].isupper() and u'  ' or u' '
        cline = len(cline) != 0 and (cline + delimiter + word) or word
      else:
        lines.append(cline)
        # Indent continuation lines of wrapped list items.
        if (self.FANCY_BULLETS and cline.startswith(u'\u2022 ') or cline.startswith(u'* ')) \
            or cline.startswith(u'   '):
          cline = u'   ' + word
        else:
          cline = word
    if len(cline) > 0:
      lines.append(cline)
    text = indent + u'\n'.join(lines)
    return text.encode('UTF-8')

# }}}1

if __name__ == '__main__':
  import sys
  if len(sys.argv) < 2:
    sys.stderr.write("mkd2vimdoc: Please provide a filename for the help file!\n")
    sys.exit(1)
  else:
    parser = mkd2vimdoc()
    print parser.convert(sys.stdin.read(), sys.argv[1])

# vim: ts=2 sw=2 et
