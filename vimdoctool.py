#!/usr/bin/env python

# Extract & combine function documentation from Vim scripts.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: April 2, 2015
# URL: http://peterodding.com/code/vim/tools/

"""
Usage: vim-doc-tool MARKDOWN_FILE

Extract the public functions and related comments (assumed to contain text in
Markdown format) from the Vim scripts in and/or below the current working
directory. The extracted documentation is combined into one chunk of text and
then this chunk of text is embedded in the Markdown document given on the
command line. The embedding requires two markers in the Markdown document:

  <!-- Start of generated documentation -->
  ...
  <!-- End of generated documentation -->

These two markers make it possible for "vim-doc-tool" to replace its own output
from previous runs.
"""

# Standard library modules.
import logging
import os
import os.path
import re
import sys
import textwrap
import time

# External dependency, install with:
#       pip install coloredlogs
import coloredlogs

# Initialize the logging subsystem.
logger = logging.getLogger('vimdoctool')
logger.setLevel(logging.INFO)
logger.addHandler(coloredlogs.ColoredStreamHandler(show_name=True))

# Compiled regular expressions used by parse_vim_script().
function_pattern = re.compile(r'^function! ([^(]+)\(')
comment_pattern = re.compile(r'^\s*"\s?(.*)$')

def main():
    """
    Command line interface for vim-doc-tool.
    """
    markdown_document = os.path.abspath(sys.argv[1])
    directory = os.path.dirname(markdown_document)
    embed_documentation(directory, markdown_document, startlevel=1)
    logger.info("Done!")

def embed_documentation(directory, filename, startlevel=1, vfs=None):
    """
    Generate up-to-date documentation and embed the documentation in the given
    Markdown document, replacing any previously embedded documentation (based
    on hidden markers in the Markdown text; special HTML comments).
    """
    doc_start = '<!-- Start of generated documentation -->'
    doc_end = '<!-- End of generated documentation -->'
    # Load Markdown document.
    logger.debug("Reading template: %s", filename)
    with open(filename) as handle:
        template = handle.read()
    if doc_start not in template:
        # Nothing to do.
        logger.warn("Markdown document %s doesn't contain start marker: %s", filename, doc_start)
        return False
    # Extract documentation from Vim scripts.
    documentation = generate_documentation(directory, startlevel=startlevel, vfs=vfs)
    # Inject documentation into Markdown document.
    documentation = "\n\n".join([doc_start, documentation, doc_end])
    pattern = re.compile(re.escape(doc_start) + '.*?' + re.escape(doc_end), re.DOTALL)
    updated_template = pattern.sub(documentation, template)
    if ignore_timestamp(updated_template) == ignore_timestamp(template):
        # Nothing was changed (except maybe the time stamp).
        return False
    # Save updated Markdown document.
    logger.debug("Writing template: %s", filename)
    with open(filename, 'w') as handle:
        handle.write(updated_template)
    return True

def generate_documentation(directory, startlevel=1, vfs=None):
    """
    Generate documentation for Vim script functions by parsing the Vim scripts
    in and/or below the current working directory, looking for function
    definitions and extracting related comments (assumed to be in Markdown
    format).
    """
    scripts = []
    num_functions = 0
    # If the caller didn't specify a VFS layer, well use the default.
    if not vfs:
        vfs = DefaultVFS(directory)
    for filename in sorted(find_vim_scripts(vfs), key=str.lower):
        parse_results = parse_vim_script(vfs, filename)
        if parse_results:
            count = len(parse_results['functions'])
            if count > 0:
                num_functions += count
                scripts.append((filename, parse_results))
    # Combine all of the documentation into a single Markdown document.
    output = [wrap("""
        The documentation of the {num_funcs} functions below was extracted from
        {num_scripts} Vim scripts on {date}.
    """).format(num_funcs=num_functions,
                num_scripts=len(scripts),
                date=compact(time.strftime('%B %e, %Y at %H:%M')))]
    for filename, parse_results in scripts:
            if parse_results['functions']:
                output.append("%s %s" % ("#" * startlevel, parse_results['synopsis']))
                if parse_results['description']:
                    output.append("\n".join(parse_results['description']))
                for function, comments in parse_results['functions']:
                    if any(line and not line.isspace() for line in comments):
                        output.append("%s The `%s()` function" % ("#" * (startlevel + 1), function))
                        output.append("\n".join(comments))
    return "\n\n".join(output)

def find_vim_scripts(vfs):
    """
    Recursively scan the current working directory for Vim scripts.
    """
    logger.info("Scanning %s for Vim scripts ..", vfs)
    for filename in vfs.list():
        if filename.endswith('.vim'):
            logger.debug("Found %s", filename)
            yield filename

def parse_vim_script(vfs, filename):
    """
    Perform a very shallow parse of a Vim script file to find function
    definitions and related comments. Returns a dictionary with the following
    keys:

    - synopsis: One line summary of purpose of Vim script
    - description: A paragraph or two explaining the purpose of the functions
      defined in the Vim script in more detail
    - functions: A list of tuples with two values each: The name of a function
      and the related comments
    """
    parse_results = dict(functions=[])
    lines = vfs.read(filename).splitlines()
    # Extract the prologue (a description of the functions in the script).
    prologue = []
    while lines:
        line = lines.pop(0)
        match = comment_pattern.match(line)
        if not match:
            break
        text = match.group(1)
        if ':' in text:
            label, value = text.split(':', 1)
            if label in ('Author', 'Last Change', 'URL'):
                continue
        prologue.append(text)
    assert len(prologue) >= 1, "Failed to extract script prologue!"
    # Extract the one-line synopsis of the script's functions.
    synopsis = prologue.pop(0).strip().rstrip('.')
    while prologue and not prologue[0].strip():
        prologue.pop(0)
    logger.debug("Extracted synopsis: %s", synopsis)
    parse_results['synopsis'] = synopsis
    parse_results['description'] = prologue
    while lines:
        line = lines.pop(0)
        match = function_pattern.match(line)
        if match:
            function_name = match.group(1)
            logger.debug("Found function: %s()", function_name)
            # Collect comments immediately following the function prologue.
            logger.debug("Extracting comments:")
            comments = []
            while lines:
                line = lines.pop(0)
                match = comment_pattern.match(line)
                if not match:
                    break
                text = match.group(1)
                logger.debug("  %s", text)
                comments.append(text)
            if is_public_function(function_name):
                parse_results['functions'].append((function_name, comments))
    num_functions = len(parse_results['functions'])
    logger.info("Found %i function%s in %s.", num_functions, '' if num_functions == 1 else 's', filename)
    return parse_results

def is_public_function(function_name):
    """
    Determine whether the Vim script function with the given name is a public
    function which should be included in the generated documentation (for
    example script-local functions are not included in the generated
    documentation).
    """
    is_global_function = ':' not in function_name and function_name[0].isupper()
    is_autoload_function = '#' in function_name and not function_name[0].isupper()
    return is_global_function or is_autoload_function

class DefaultVFS(object):

    """
    Default virtual file system interface which simple looks at the working
    directory. Easy to replace with a VFS that looks at the git HEAD.
    """

    def __init__(self, root):
        self.root = os.path.abspath(root)

    def __str__(self):
        return self.root

    def list(self):
        for directory, dirs, files in os.walk(self.root):
            for filename in files:
                pathname = os.path.join(directory, filename)
                yield os.path.relpath(pathname, self.root)

    def read(self, filename):
        pathname = os.path.join(self.root, filename)
        with open(pathname) as handle:
            return handle.read()

def wrap(text):
    """
    Hard wrap a paragraph of text.
    """
    return "\n".join(textwrap.wrap(compact(text), 79))

def compact(text):
    """
    Compact whitespace in a string.
    """
    return " ".join(text.split())

def ignore_timestamp(text):
    """
    Remove a time stamp from a string to ease comparison.

    This function removes timestamps generated using the following method::

        time.strftime('%B %e, %Y at %H:%M')

    This makes it easy to compare two strings for equality without even though
    the embedded timestamps may differ.
    """
    return re.sub(r'\w+\s+\d{1,2},\s+\d{4}\s+at\s+\d\d:\d\d', '', text)

if __name__ == '__main__':
    main()

# vim: ft=python ts=4 sw=4 et
