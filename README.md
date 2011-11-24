# Python scripts to publish Vim plug-ins

I'm a programmer which naturally means I hate performing repetitive tasks... Publishing [my Vim plug-ins] [homepage] quickly turned out to fall in this category; I'd keep making the same mistakes and having users e-mail me because I screwed up again and uploaded a broken release to [www.vim.org] [vim_online]. After a while this got embarrassing so I decided to solve this annoying problem once and for all. This git repository contains the results in the form of two Python scripts:

## vim-plugin-release

This program makes it easier for me to publish my Vim plug-ins on GitHub and Vim Online. This is what I use to publish my plug-ins on <http://www.vim.org>. It might be a bit specific to my workflow but you never know, someone might find it useful :-)

## mkd2vimdoc.py

This Python module converts Markdown formatted text to Vim's help file format. I created this code because I write a `README.md` document for every project I publish on GitHub and thought it would be nice to include these documents in a more readable format with the ZIP archives I upload to <http://www.vim.org>. The code is basically one big hack, desperately trying to avoid becoming a multi pass parser but it works and I'm happy with it, so there ;-)

## html2vimdoc.py

This Python script works in the same way as `mkd2vimdoc.py` except that it takes HTML as input which makes it more flexible, for example I use it to convert the [Lua](http://www.lua.org/manual/5.1/manual.html), [LPeg](http://www.inf.puc-rio.br/~roberto/lpeg/lpeg.html) and [Lua/APR](http://peterodding.com/code/lua/apr/docs) manuals to Vim's help file format. This script already does more than `mkd2vimdoc.py` but it still has some warts I want to fix before I forget about `mkd2vimdoc.py` and switch to `html2vimdoc.py` completely.

[homepage]: http://peterodding.com/code/vim/
[vim_online]: http://www.vim.org/account/profile.php?user_id=14483
