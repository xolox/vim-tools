# Python scripts to publish Vim plug-ins

I'm a programmer which naturally means I hate performing repetitive tasks...
Publishing [my Vim plug-ins] [homepage] quickly turned out to fall in this
category; I'd keep making the same mistakes and having users e-mail me because
I screwed up again and uploaded a broken release to [www.vim.org] [vim-online].
After a while this got embarrassing so I decided to solve this annoying problem
once and for all.

Things started out small but as my existing Vim plug-ins mature and I publish
more Vim plug-ins to the world, the `vim-tools` repository grows with me. It
now contains several Python modules which can be useful to other people (mostly
Vim plug-in developers) which is why I'm sharing it with the world.

## html2vimdoc

The Python module `html2vimdoc.py` converts [Markdown] [md] and HTML documents
to Vim help files.

### Features

- It can deal with complex HTML thanks to [BeautifulSoup] [bs]
- Automatically generates Vim help file tags for headings
- Generates table of contents from headings & tags
- Supports nested block structures like nested lists, preformatted blocks
  inside lists, etc.
- Compacts & expands list items based on average number of lines per list item

### Usage

It has a command line interface but can also be used as a plain Python module.

### Dependencies

The `html2vimdoc.py` module has several dependencies, the easiest way to
install them is in a [Python virtual environment] [virtualenv]:

    # Clone the repository
    git clone https://github.com/xolox/vim-tools.git
    cd vim-tools

    # Create the virtual environment.
    virtualenv html2vimdoc

    # Install the dependencies.
    html2vimdoc/bin/pip install beautifulsoup coloredlogs markdown

    # Run the program.
    html2vimdoc/bin/python ./html2vimdoc.py --help

### How I use it

I use this module to convert my Vim plug-in `README.md` files and the [Lua]
[lua], [LPeg] [lpeg] and [Lua/APR] [lua-apr] manuals to Vim's help file format.
Here's my workflow involving the documentation of my Vim plug-ins:

- I write the documentation of my Vim plug-ins in `README.md` files because
  [GitHub] [gh] renders such files as a "repository homepage".
- A git pre-commit hook runs `html2vimdoc.py` to convert `README.md` file to a
  Vim help file which is included in the commit.
- When I push a new version of a plug-in to [GitHub] [gh], it will trigger a
  web hook which notifies my personal website. The latest version of
  `README.md` is fetched and used as the plug-in homepage on my website.

## vimdoctool

The Python module `vimdoctool.py` extracts the public functions and related
comments (assumed to contain text in [Markdown] [md] format) from the Vim
scripts in and/or below the current working directory. The extracted
documentation is combined into one chunk of text and then this chunk of text is
embedded in the Markdown document given on the command line.

I use this module to publish the documentation of my [vim-misc] [vim-misc]
scripts.

### Dependencies

This module has a dependency on my [coloredlogs] [cl] module which is available
on PyPi (the Python package index).

## vim-plugin-manager

This program (written in Python) makes it easier for me to publish my Vim
plug-ins on [GitHub] [gh] and [Vim Online] [vim-online]. It automates most of
my release management, here's a short summary:

- Run as a git pre-commit hook:
    1. Make sure `doc/tags` is included in `.gitignore`
    2. Make sure the copyright in `README.md` is up to date
    3. Run `vimdoctool.py` to update function documentation embedded in
       `README.md`
    4. Run `html2vimdoc.py` to update Vim help file based on `README.md`
- Run as a git post-commit hook:
    - Make sure git tags are created for version bumps on the `master` branch
- Interactively, for one of two reasons:
    - Publish the latest version of a Vim plug-in to [GitHub] [gh] and [Vim
      Online] [vim-online] (`vim-plugin-manager -r`):
        1. First this pushes the latest commits and tags to [GitHub] [gh]
        2. Then it checks what was the last release uploaded to [Vim Online]
           [vim-online]
        3. Based on the last uploaded release a change log is generated from
           the git history
        4. Vim is opened to approve the change log and allow changes to the
           contents
        5. The command `git archive` is used to generate a ZIP archive with a
           clean copy (no local changes) of the last commit
        6. The approved change log and ZIP archive are combined into a new
           release which is posted to [Vim Online] [vim-online] using
           [Mechanize] [mn]
    - Summarize the local changes in my Vim plug-in repositories
      (`vim-plugin-manager -c`)

It might be a bit specific to my workflow but you never know, someone might
find it useful :-)

## Contact

If you have questions, bug reports, suggestions, etc. the author can be
contacted at <peter@peterodding.com>. The latest version is available at
<http://peterodding.com/code/vim/tools/> and
<http://github.com/xolox/vim-tools>.

## License

This software is licensed under the [MIT license] [mit].  
© 2013 Peter Odding &lt;<peter@peterodding.com>&gt;.

The `html2vimdoc.py` module bundles `soupselect.py` by Simon Willison. The
soupselect module is also licensed under the [MIT license] [mit]. You can find
the soupselect module on [GitHub] [ss-gh] and [Google Code] [ss-gc].


[bs]: http://www.crummy.com/software/BeautifulSoup/
[cl]: https://pypi.python.org/pypi/coloredlogs/0.2
[gh]: https://github.com/xolox
[homepage]: http://peterodding.com/code/vim/
[lpeg]: http://www.inf.puc-rio.br/~roberto/lpeg/lpeg.html
[lua-apr]: http://peterodding.com/code/lua/apr/docs
[lua]: http://www.lua.org/manual/5.1/manual.html
[md]: http://en.wikipedia.org/wiki/Markdown
[mit]: http://en.wikipedia.org/wiki/MIT_License
[mn]: https://pypi.python.org/pypi/mechanize/
[ss-gc]: https://code.google.com/p/soupselect/
[ss-gh]: https://github.com/simonw/soupselect
[vim-misc]: http://peterodding.com/code/vim/misc/
[vim-online]: http://www.vim.org/account/profile.php?user_id=14483
[virtualenv]: http://www.virtualenv.org/
