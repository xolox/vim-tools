#!/usr/bin/env python
# vim: set fileencoding=utf-8 :

# Publish Vim plug-ins to GitHub and Vim Online.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: April 2, 2015
# URL: http://peterodding.com/code/vim/tools/
#
# TODO Automatically run tests before release? (first have to start writing them!)

"""
Usage: vim-plugin-manager [OPTIONS]

Publish Vim plug-ins to GitHub and/or Vim Online using a highly
automated workflow that includes the following steps:

 1. Find the previous release on Vim Online;
 2. Determine the release about to be published;
 3. Publish the changes and tags to GitHub;
 4. Generate a change log from the commit log;
 5. Approve the change log for use on Vim Online;
 6. Generate a release archive and upload it to Vim Online;
 7. Open the Vim Online page of the plug-in to review the result;
 8. Run a post-release hook for any further custom handling.

Supported options:
  -n, --dry-run        don't actually upload anything anywhere
  -i, --install        install shared pre/post commit hooks
  -p, --pre-commit     run shared pre-commit hooks
  -P, --post-commit    run shared post-commit hooks
  -r, --release        release to GitHub [and Vim Online]
  -c, --changes        summarize uncommitted changes
  -v, --verbose        make more noise
  -h, --help           show this message and exit
"""

# Standard library modules.
import codecs
import ConfigParser
import getopt
import json
import logging
import netrc
import os
import re
import subprocess
import sys
import textwrap
import time
import urllib
import webbrowser

# External dependency, install with:
#  apt-get install python-mechanize
#  pip install mechanize
import mechanize

# External dependency, install with:
#  pip install coloredlogs
import coloredlogs

# External dependency, install with:
#  pip install verboselogs
import verboselogs

# External dependencies bundled with the Vim plug-in manager.
import html2vimdoc, vimdoctool

def main():

    """
    Command line interface for the Vim plug-in manager.
    """

    # Parse the command line arguments.
    try:
        options, arguments = getopt.getopt(sys.argv[1:], 'nipPrcvh',
                ['dry-run', 'install', 'pre-commit', 'post-commit', 'release',
                    'changes' 'verbose', 'help'])
    except Exception, e:
        sys.stderr.write("Error: %s\n\n" % e)
        usage()
        sys.exit(1)

    # Command line option defaults.
    dry_run = False
    verbosity = 0
    install = False
    pre_commit = False
    post_commit = False
    release = False
    changes = False

    # Map options to variables.
    for option, value in options:
        if option in ('-n', '--dry-run'):
            dry_run = True
        elif option in ('-i', '--install'):
            install = True
        elif option in ('-p', '--pre-commit'):
            pre_commit = True
        elif option in ('-P', '--post-commit'):
            post_commit = True
        elif option in ('-r', '--release'):
            release = True
        elif option in ('-c', '--changes'):
            changes = True
        elif option in ('-v', '--verbose'):
            verbosity += 1
        elif option in ('-h', '--help'):
            usage()
            return
        else:
            assert False, "Unhandled option!"

    if not (install or pre_commit or post_commit or release or changes):
        usage()
    else:
        # Initialize the Vim plug-in manager with the selected options.
        manager = VimPluginManager(dry_run=dry_run, verbosity=verbosity)
        # Execute the requested action.
        if install:
            manager.install_git_hooks()
        if pre_commit:
            manager.run_precommit_hooks()
        if post_commit:
            manager.run_postcommit_hooks()
        if release:
            manager.publish_release(manager.find_current_plugin())
        if changes:
            manager.summarize_uncommitted_changes()

def usage():
    sys.stdout.write("%s\n" % __doc__.strip())

class VimPluginManager:

    """
    The Vim plug-in manager is implemented as a class because it has quite a
    bit of internal state (specifically configuration and logging) and
    classes/objects provide a nice way to encapsulate this.
    """

    ## Initialization.

    def __init__(self, dry_run=False, verbosity=0):
        """
        Initialize the internal state of the Vim plug-in manager, including the
        configuration and logging subsystems.
        """
        self.plugins = {}
        self.dry_run = dry_run
        self.initialize_logging(verbosity)
        self.load_configuration()
        if dry_run:
            self.logger.info("Enabling dry run.")

    def initialize_logging(self, verbosity):
        """
        Initialize the logging subsystem.
        """
        # Create a logger instance.
        self.logger = verboselogs.VerboseLogger('vim-plugin-manager')
        self.set_log_level(logging.DEBUG)
        # Add a handler for logging to a file.
        log_file = os.path.expanduser('~/.vim-plugin-manager.log')
        log_exists = os.path.isfile(log_file)
        file_handler = coloredlogs.ColoredStreamHandler(open(log_file, 'a'), show_name=True, isatty=False)
        self.logger.addHandler(file_handler)
        # The log file is always verbose.
        file_handler.setLevel(logging.DEBUG)
        # Add a delimiter to the log file to delimit the messages of the
        # current run from those of previous runs.
        if log_exists:
            self.logger.info("-" * 40)
        # Add a logging handler for console output, after logging the delimiter
        # to the log file (the delimiter is useless on the console).
        console_handler = coloredlogs.ColoredStreamHandler(show_name=True)
        self.logger.addHandler(console_handler)
        # Set the verbosity of the console output.
        if verbosity >= 2:
            self.set_log_level(logging.DEBUG)
            self.logger.debug("Enabling debugging output.")
        elif verbosity == 1:
            self.set_log_level(logging.VERBOSE)
            self.logger.verbose("Enabling verbose output.")
        else:
            self.set_log_level(logging.INFO)
        # Mention the log file on the console after setting the verbosity?
        self.logger.debug("Logging messages to %s.", log_file)

    def set_log_level(self, level):
        """
        Set the log verbosity of the Vim plug-in manager & related modules.
        """
        self.logger.setLevel(level)
        html2vimdoc.logger.setLevel(level)
        vimdoctool.logger.setLevel(level)

    def load_configuration(self):
        """
        Load the configuration file with plug-in definitions.
        """
        filename = os.path.expanduser('~/.vimplugins')
        self.logger.verbose("Loading configuration from %s ..", filename)
        parser = ConfigParser.RawConfigParser()
        parser.read(filename)
        for plugin_name in parser.sections():
            self.logger.debug("Loading plug-in: %s", plugin_name)
            items = dict(parser.items(plugin_name))
            items['name'] = plugin_name
            directory = os.path.expanduser(items['directory'])
            if not os.path.isdir('%s/.git' % directory):
                msg = "Configuration error: The directory %s is not a git repository!"
                raise Exception, msg % directory
            items['directory'] = directory
            self.plugins[plugin_name] = items

    ## Management of uncommitted changes.

    def summarize_uncommitted_changes(self):
        """
        Generate a summary of the uncommitted changes in the git repositories
        of my Vim plug-ins. Sometimes I get into a refactoring spree with
        changes in several plug-ins going on at the same time; this makes it
        easier to keep track of what's going on.

        In case anyone is curious: The overview is in the format of my
        vim-notes plug-in (I love it when I can integrate my tooling :-)
        """
        output = ["Uncommitted changes to Vim plug-ins"]
        for plugin in self.sorted_plugins:
            branch_name = self.current_branch(plugin['name'])
            uncommitted_changes = self.find_uncommitted_changes(plugin['name'])
            if uncommitted_changes:
                num_files_changed = len(uncommitted_changes)
                output.append("# %s (%s)" % (plugin['name'].split('/')[-1],
                                             "%i file%s with changes" % (num_files_changed, '' if num_files_changed == 1 else 's')))
                output.append("On branch: %s" % branch_name)
                if len(uncommitted_changes) == 1:
                    output.append("The following file has uncommitted changes:")
                else:
                    output.append("The following files have uncommitted changes:")
                changed_files = []
                for filename in uncommitted_changes:
                    pathname = os.path.join(plugin['directory'], filename)
                    changed_files.append(" • %s" % pathname.replace(os.environ['HOME'], '~'))
                output.append("\n".join(changed_files))
                output.append("Differences from HEAD:")
                output.append("{{{diff\n%s\n}}}" % run('git', 'diff', 'HEAD', cwd=plugin['directory'], capture=True))
        if len(output) == 1:
            self.logger.info("No uncommitted changes found :-)")
        else:
            summary = "\n\n".join(output)
            vim_commands = ['set bg=light ft=notes ro noma nomod', 'colorscheme earendel_diff', 'let &titlestring = getline(1)']
            run('gvim', '-c', ' | '.join(vim_commands), '-', input=summary)

    ## Release management.

    def publish_release(self, plugin_name):
        """
        The main function of the Vim plug-in manager: Publishing new releases
        to GitHub and Vim Online.
        """
        try:
            if self.dry_run:
                self.logger.warn("Skipping GitHub push because we're doing a dry run.")
            else:
                self.publish_changes_to_github(plugin_name)
            if 'script-id' not in self.plugins[plugin_name]:
                self.logger.info("The plug-in %s does not have a script-id, so can't be published to vim.org.", plugin_name)
                return
            previous_release = self.find_version_on_vim_online(plugin_name)
            committed_version = self.find_version_in_repository(plugin_name)
            if committed_version == previous_release:
                self.logger.info("Everything up to date!")
            else:
                suggested_changelog = self.generate_changelog(plugin_name, previous_release, committed_version)
                approved_changelog = self.approve_changelog(suggested_changelog)
                if not approved_changelog.strip():
                    self.logger.error("Empty change log, canceling release ..")
                elif self.dry_run:
                    self.logger.warn("Skipping Vim Online release because we're doing a dry run.")
                else:
                    self.publish_release_to_vim_online(plugin_name, committed_version, approved_changelog)
                    self.show_release_on_vim_online(plugin_name)
                    self.run_post_release_hook(plugin_name)
                    self.logger.info("Done!")
        except ExternalCommandFailed, e:
            self.logger.fatal("External command failed: %s", ' '.join(e.command))
            self.logger.exception(e)
            sys.exit(1)
        except Exception, e:
            self.logger.exception(e)
            sys.exit(1)

    def publish_changes_to_github(self, plugin_name):
        """
        Publish committed changes and tags to the remote repository on GitHub.
        """
        self.logger.info("Pushing change sets to GitHub ..")
        directory = self.plugins[plugin_name]['directory']
        run('git', 'push', 'origin', 'master', cwd=directory)
        run('git', 'push', '--tags', cwd=directory)

    def find_version_on_vim_online(self, plugin_name):
        """
        Find the version of a Vim plug-in that is the highest version number
        that has been released on http://www.vim.org.
        """
        # Find the Vim plug-in on http://www.vim.org.
        script_id = self.plugins[plugin_name]['script-id']
        vim_online_url = 'http://www.vim.org/scripts/script.php?script_id=%s' % script_id
        self.logger.debug("Finding last released version on %s ..", vim_online_url)
        response = urllib.urlopen(vim_online_url)
        # Make sure the response is valid.
        if response.getcode() != 200:
            msg = "URL %r resulted in HTTP %i response!"
            raise Exception, msg % (vim_online_url, response.getcode())
        # Find all previously released versions by scraping the HTML.
        released_versions = []
        for html_row in re.findall('<tr>.+?</tr>', response.read(), re.DOTALL):
            if 'download_script.php' in html_row:
                version_string = re.search('<b>(\d+(?:\.\d+)+)</b>', html_row).group(1)
                version_number = map(int, version_string.split('.'))
                self.logger.log(logging.NOTSET, "Parsed version string %r into %r.", version_string, version_number)
                released_versions.append(version_number)
        # Make sure the scraping is still effective.
        if not released_versions:
            msg = "Failed to find any previous releases on %r!"
            raise Exception, msg % vim_online_url
        self.logger.debug("Found %i previous releases, sorting to find the latest ..", len(released_versions))
        released_versions.sort()
        previous_release = '.'.join([str(d) for d in released_versions[-1]])
        self.logger.info("Found last release on Vim Online: %s", previous_release)
        return previous_release

    def generate_changelog(self, plugin_name, previous_version, current_version):
        """
        Generate a change log from the one-line messages of all commits between
        the previous release and the current one combined with links to the
        commits on GitHub.
        """
        # Find the current tag in the local git repository.
        self.logger.debug("Generating change log based on git commits & tags ..")
        # Generate a range for git log to find all commits between the previous
        # release and the current one.
        commit_range = previous_version + '..' + current_version
        # Generate the change log from the abbreviated commit message(s).
        items = []
        repo_url = 'http://github.com/%s' % plugin_name
        commit_log = run('git', 'log', '--pretty=oneline', '--abbrev-commit', commit_range,
                         cwd=self.plugins[plugin_name]['directory'],
                         capture=True)
        for line in reversed(commit_log.splitlines()):
            commit_hash, commit_desc = line.split(None, 1)
            items.append(' \x95 %s:\n' % commit_desc.strip().rstrip(':') +
                             '   %s/commit/%s' % (repo_url, commit_hash))
        changelog = '\n\n'.join(items)
        for line in changelog.splitlines():
            self.logger.debug("%s", cp1252_to_utf8(line))
        return changelog

    def approve_changelog(self, changelog):
        """
        Open the suggested change log in a text editor so the user gets a
        chance to inspect the suggested change log, make any required changes
        or clear the change log to abort the release.
        """
        # Save the change log to a temporary file.
        fname = '/tmp/vim-online-changelog'
        with open(fname, 'w') as handle:
            handle.write(changelog)
        # Run Vim with the cp1252 encoding because this is the encoding
        # expected by http://www.vim.org.
        self.logger.info("Waiting for approval of change log ..")
        run('gvim', '--noplugin', '-fc', 'e ++enc=cp1252 %s' % fname)
        # Get the approved change log.
        with open(fname) as handle:
            changelog = handle.read().rstrip()
        os.unlink(fname)
        # Log the approved change log.
        for line in changelog.splitlines():
            self.logger.debug("%s", cp1252_to_utf8(line))
        return changelog

    def publish_release_to_vim_online(self, plugin_name, new_version, changelog):
        """
        Automatically publish a new release to Vim Online without opening an
        actual web browser (scripted HTTP exchange using Mechanize module).
        """
        self.logger.info("Preparing to upload release to Vim Online ..")
        # Find the username & password in the ~/.netrc file.
        user_netrc = netrc.netrc(os.path.expanduser('~/.netrc'))
        username, _, password = user_netrc.hosts['www.vim.org']
        # Find the script ID in the plug-in configuration.
        script_id = int(self.plugins[plugin_name]['script-id'])
        # Generate the ZIP archive and up-load it.
        zip_archive = self.generate_release_archive(plugin_name)
        with open(zip_archive) as zip_handle:
            self.logger.info("Uploading release to Vim Online (please be patient) ..")
            # Open a session to Vim Online.
            add_script_url = "http://www.vim.org/scripts/add_script_version.php?script_id=%i" % script_id
            self.logger.debug("Connecting to Vim Online at %s ..", add_script_url)
            session = mechanize.Browser()
            session.open(add_script_url)
            # Fill in the login form.
            self.logger.debug("Logging in on Vim Online ..")
            session.select_form('login')
            session['userName'] = username
            session['password'] = password
            session.submit()
            # Fill in the upload form.
            self.logger.debug("Uploading release archive to Vim Online ..")
            session.select_form('script')
            session['vim_version'] = ['7.0']
            session['script_version'] = new_version
            session['version_comment'] = changelog
            session.form.add_file(zip_handle, 'application/zip', os.path.basename(zip_archive), 'script_file')
            session.submit()
            self.logger.info("Finished uploading release archive!")
        # Cleanup the release archive.
        os.unlink(zip_archive)

    def generate_release_archive(self, plugin_name):
        """
        Generate a ZIP archive from the HEAD of the local git repository (clean
        of any local changes and/or uncommitted files).
        """
        filename = '/tmp/%s' % self.plugins[plugin_name]['zip-file']
        self.logger.info("Saving ZIP archive of HEAD to %s ..", filename)
        run('git', 'archive', '-o', filename, 'HEAD',
            cwd=self.plugins[plugin_name]['directory'])
        return filename

    def show_release_on_vim_online(self, plugin_name):
        """
        Open the Vim Online web page of the Vim plug-in in a web browser so the
        user can verify that the new release was successfully uploaded.
        """
        script_id = int(self.plugins[plugin_name]['script-id'])
        webbrowser.open('http://www.vim.org/scripts/script.php?script_id=%d' % script_id)

    def run_post_release_hook(self, plugin_name):
        """
        Run a custom script after publishing the latest release to GitHub and
        Vim Online. In my case this script updates the link to the latest ZIP
        archive on peterodding.com to make sure I don't serve old downloads
        after releasing a new version.
        """
        self.logger.debug("Checking for post-release hook ..")
        try:
            pathname = run('which', 'after-vim-plugin-release', capture=True)
        except ExternalCommandFailed:
            # The hook is not installed.
            self.logger.debug("No post-release hook installed!")
        else:
            self.logger.info("Running post-release hook %s ..", pathname)
            run(pathname)

    ## Git hook management.

    def install_git_hooks(self):
        """
        Install wrapper scripts for the shared git hooks.
        """
        self.logger.info("Installing git hooks ..")
        for plugin in self.sorted_plugins:
            repository = plugin['directory']
            directory = '%s/.git/hooks' % repository
            if not os.path.isdir(directory):
                os.mkdir(directory)
            else:
                self.logger.debug("Deleting old hooks in %s ..", repository)
                for entry in os.listdir(directory):
                    os.unlink('%s/%s' % (directory, entry))
            self.create_hook_script(repository, '%s/pre-commit' % directory)
            self.create_hook_script(repository, '%s/post-commit' % directory)
        self.logger.info("Done. Created git hooks for %i plug-ins.", len(self.plugins))

    def create_hook_script(self, repository, hook_path):
        """
        Create a git hook using a small wrapper script instead of a symbolic
        link. I keep my Vim profile and the git repositories of my plug-ins in
        my Dropbox and unfortunately Dropbox does not support symbolic links
        (it doesn't synchronize the link, it synchronizes the content, so the
        actual symbolic link only exists on the machine where it was created).
        """
        self.logger.debug("Creating hook script: %s", hook_path)
        hook_name = os.path.basename(hook_path)
        # The hook scripts become part of my Dropbox, synced between Mac OS X
        # and Linux. For this reason we generate a relative path to the
        # vim-plugin-manager script so that the hook works on both Linux
        # (/home/*) and Mac OS X (/Users/*).
        relpath = os.path.relpath(__file__, repository)
        with open(hook_path, 'w') as handle:
            handle.write(textwrap.dedent("""
                #!/bin/bash

                # Generated git {hook_name} hook.

                if [ -z "$DISABLE_GIT_HOOKS" ]; then
                  exec {relpath} --{hook_name}
                fi
            """).lstrip().format(relpath=relpath, hook_name=hook_name))
        os.chmod(hook_path, 0755)

    ## Pre-commit hooks.

    def run_precommit_hooks(self):
        """
        Automatic plug-in/repository maintenance just before a commit is made.
        """
        self.logger.info("Running pre-commit hooks ..")
        plugin_name = self.find_current_plugin()
        self.check_gitignore_file(plugin_name)
        self.update_vam_addon_info(plugin_name)
        self.update_copyright(plugin_name)
        self.update_install_instructions(plugin_name)
        self.run_vimdoctool(plugin_name)
        self.run_html2vimdoc(plugin_name)

    def check_gitignore_file(self, plugin_name):
        """
        Make sure .gitignore excludes doc/tags.
        """
        self.logger.verbose("Checking if .gitignore excludes doc/tags ..")
        # Make sure there is an initial commit, otherwise git on Ubuntu 10.04
        # will error out with "fatal: No HEAD commit to compare with (yet)".
        self.logger.verbose("Checking whether there is an initial commit ..")
        try:
            run('git', 'rev-parse', 'HEAD', silent=True)
        except ExternalCommandFailed:
            self.logger.warn("No initial commit yet, can't check .gitignore!")
            return
        # There is an initial commit: We can check the .gitignore file!
        if ('doc/tags' not in self.get_committed_contents(plugin_name, '.gitignore').splitlines() and
            'doc/tags' not in self.get_staged_contents(plugin_name, '.gitignore').splitlines()):
            self.logger.fatal("The .gitignore file does not exclude doc/tags! Please resolve before committing.")
            sys.exit(1)

    def update_vam_addon_info(self, plugin_name):
        """
        Make sure addon-info.json is up to date. This file is used by
        vim-addon-manager (VAM).
        """
        self.logger.verbose("Updating addon-info.json ..")
        directory = self.plugins[plugin_name]['directory']
        addon_info_file = os.path.join(directory, 'addon-info.json')
        addon_info = dict(name=plugin_name.split('/')[-1],
                          homepage=self.plugins[plugin_name]['homepage'],
                          dependencies=dict())
        if self.depends_on_vim_misc(plugin_name):
            addon_info['dependencies']['vim-misc'] = dict()
        if 'script-id' in self.plugins[plugin_name]:
            addon_info['vim_script_nr'] = int(self.plugins[plugin_name]['script-id'])
        with open(addon_info_file, 'w') as handle:
            handle.write(json.dumps(addon_info))
        run('git', 'add', addon_info_file, cwd=directory)

    def update_copyright(self, plugin_name):
        """
        Update the year of copyright in README.md when needed.
        """
        contents = []
        updated_copyright = False
        self.logger.verbose("Checking if copyright in README is up to date ..")
        directory = self.plugins[plugin_name]['directory']
        filename = os.path.join(directory, 'README.md')
        with codecs.open(filename, 'r', 'utf-8') as handle:
            for line in handle:
                line = line.rstrip()
                if line.startswith(u'©'):
                    replacement = u'© %s' % time.strftime('%Y')
                    new_line = re.sub(ur'© \d{4}', replacement, line)
                    if new_line != line:
                        updated_copyright = True
                    line = new_line
                contents.append(line)
        if updated_copyright:
            self.logger.info("Copyright in README was not up to date, changing it now ..")
            with codecs.open(filename, 'w', 'utf-8') as handle:
                for line in contents:
                    handle.write(u'%s\n' % line)
            run('git', 'add', 'README.md', cwd=directory)

    def update_install_instructions(self, plugin_name):
        """
        Generate ``INSTALL.md``.

        Over time I've learned that most people perusing GitHub don't read
        through the ``README.md`` files in my projects before trying them out,
        so I moved the installation instructions to separate (easy to
        recognize) files called ``INSTALL.md`` to avoid people missing the
        installation instructions and submitting bug reports about things that
        are clearly documented.

        However there are more similarities than differences between the
        installation instructions for my 10+ Vim plug-ins and I got sick of
        propagating common changes between git repositories manually, so
        eventually I wrote the following code that alleviates me from the
        tedium of keeping these files in sync.
        """
        directory = self.plugins[plugin_name]['directory']
        install_file = os.path.join(directory, 'INSTALL.md')
        self.logger.info("Generating %s ..", install_file)
        repository_name = plugin_name.split('/')[-1]
        vim_misc_required = self.depends_on_vim_misc(plugin_name)
        instructions = ["# Installation instructions"]
        if vim_misc_required:
            instructions.append(compact("""
                *Please note that the {name} plug-in requires my vim-misc
                plug-in which is separately distributed.*
            """, name=repository_name))
        instructions.append(compact("""
            There are two ways to install the {name} plug-in and it's up to you
            which you prefer, both options are explained below. Please note
            that below are generic installation instructions while some Vim
            plug-ins may have external dependencies, please refer to the
            plug-in's [readme](README.md) for details.
        """, name=repository_name))
        instructions.append(compact("""
            ## Installation using {zip_archives}
        """, zip_archives="ZIP archives" if vim_misc_required else "a ZIP archive"))
        base_download_url = "http://peterodding.com/code/vim/downloads"
        download_link = compact("""
            [{name}]({base_url}/{zip_file})
        """,  name=repository_name,
              base_url=base_download_url,
              zip_file=self.plugins[plugin_name]['zip-file'])
        if vim_misc_required:
            zip_archives = compact("""
                ZIP archives of the {download_link} and
                [vim-misc]({base_url}/misc.zip) plug-ins
            """, download_link=download_link,
                 base_url=base_download_url)
        else:
            zip_archives = compact("""
                ZIP archive of the {download_link} plug-in
            """, download_link=download_link)
        instructions.append(compact(r"""
            Unzip the most recent {zip_archives} inside your Vim profile
            directory (usually this is `~/.vim` on UNIX and
            `%USERPROFILE%\vimfiles` on Windows), restart Vim and execute the
            command `:helptags ~/.vim/doc` (use `:helptags ~\vimfiles\doc`
            instead on Windows).
        """, zip_archives=zip_archives))
        instructions.append(compact("""
            If you get warnings about overwriting existing files while
            unpacking the {archives} you probably don't need to worry about
            this because it's most likely caused by files like `README.md`,
            `INSTALL.md` and `addon-info.json`. If these files bother you then
            you can remove them after unpacking the {archives}, they are not
            required to use the plug-in.
        """, archives="ZIP archives" if vim_misc_required else "ZIP archive"))
        instructions.append("## Installation using a Vim plug-in manager")
        repo_link = compact("""
            [{name}](https://github.com/{github_repo})
        """, name=repository_name,
             github_repo=plugin_name)
        if vim_misc_required:
            git_repos = compact("""
                {repo_link} and [vim-misc](https://github.com/xolox/vim-misc)
                plug-ins using local clones of the git repositories
            """, repo_link=repo_link)
        else:
            git_repos = compact("""
                {repo_link} plug-in using a local clone of the git repository
            """, repo_link=repo_link)
        instructions.append(compact("""
            If you prefer you can also use
            [Pathogen](http://www.vim.org/scripts/script.php?script_id=2332),
            [Vundle](https://github.com/gmarik/vundle) or a similar tool to
            install and update the {git_repos}. This takes a bit of work to
            set up the first time but it makes updating much easier, and it
            keeps each plug-in in its own directory which helps to keep your
            Vim profile uncluttered.
        """, git_repos=git_repos))
        with open(install_file, 'w') as handle:
            handle.write("\n\n".join(instructions) + "\n")
        run('git', 'add', 'INSTALL.md', cwd=directory)

    def run_vimdoctool(self, plugin_name):
        """
        Update the function documentation embedded in README.md using the
        vimdoctool.py Python module.
        """
        directory = self.plugins[plugin_name]['directory']
        readme = os.path.join(directory, 'README.md')
        self.logger.info("Updating embedded documentation in %s ..", readme)
        if vimdoctool.embed_documentation(directory, readme,
                                          startlevel=3,
                                          vfs=GitVFS(directory)):
            # Only `git add' the file when changes were made.
            run('git', 'add', 'README.md', cwd=directory)

    def run_html2vimdoc(self, plugin_name):
        """
        Generate a Vim help file from the README.md file in the git repository
        of a Vim plug-in using the html2vimdoc.py Python module.
        """
        directory = self.plugins[plugin_name]['directory']
        vfs = GitVFS(directory)
        readme = os.path.join(directory, 'README.md')
        help_dir = os.path.join(directory, 'doc')
        help_file = self.plugins[plugin_name]['help-file']
        help_path = os.path.join(help_dir, help_file)
        self.logger.info("Converting %s to %s ..", readme, help_path)
        markdown = vfs.read('README.md')
        html = html2vimdoc.markdown_to_html(markdown, [])
        vimdoc = html2vimdoc.html2vimdoc(html, filename=help_file)
        if not os.path.isdir(help_dir):
            os.mkdir(help_dir)
        with codecs.open(help_path, 'w', 'utf-8') as handle:
            handle.write("%s\n" % vimdoc)
        run('git', 'add', help_path, cwd=directory)

    def depends_on_vim_misc(self, plugin_name):
        """
        Check whether a Vim plug-in depends on the vim-misc plug-in.

        This method inspects the ``*.vim`` files in the git repository for
        references to ``xolox#misc#*`` which is a simple and naive way to check
        for the vim-misc dependency. It can be fooled (it's not really aware of
        Vim script syntax rules) but it suffices for me.
        """
        if plugin_name != 'xolox/vim-misc':
            # Use the GitVFS class to scan the repository without getting
            # confused by uncommitted changes or files.
            directory = self.plugins[plugin_name]['directory']
            vfs = GitVFS(directory)
            for filename in vfs.list():
                if filename.endswith('.vim'):
                    contents = vfs.read(filename)
                    for line in contents.splitlines():
                        line = line.strip()
                        # Ignore comments (lines starting with a double quote).
                        if not line.startswith('"'):
                            if 'xolox#misc#' in contents:
                                return True
        return False

    ## Post-commit hooks.

    def run_postcommit_hooks(self):
        """
        Automatic plug-in/repository maintenance just after a commit is made.
        """
        self.logger.info("Running post-commit hooks ..")
        self.tag_release(self.find_current_plugin())

    def tag_release(self, plugin_name):
        """
        Automatically tag releases.
        """
        if self.current_branch(plugin_name) != 'master':
            self.logger.debug("Not on master branch: skipping release tag.")
            return
        version = self.find_version_in_repository(plugin_name)
        if version in self.find_releases(plugin_name):
            self.logger.debug("Tag %s already exists ..", version)
        else:
            self.logger.info("Creating tag for version %s ..", version)
            run('git', 'tag', version, cwd=self.plugins[plugin_name]['directory'])

    ## Miscellaneous methods.

    @property
    def sorted_plugins(self):
        """
        List of Vim plug-in objects (dictionaries) sorted by lowercase plug-in name.
        """
        def sort_key(plugin):
            user, repository = plugin['name'].split('/', 1)
            return repository.lower()
        return sorted(self.plugins.values(), key=sort_key)

    def find_current_plugin(self):
        """
        Find the name of the "current" plug-in based on the current working
        directory.
        """
        self.logger.debug("Finding current plug-in based on current working directory ..")
        current_directory = os.path.realpath('.')
        for plugin_name, info in self.plugins.iteritems():
            directory = os.path.realpath(info['directory'])
            if current_directory.startswith(directory):
                self.logger.info("Current plug-in is %r.", plugin_name)
                return plugin_name
        msg = "The directory %r doesn't contain a known Vim plug-in!"
        raise Exception, msg % current_directory

    def current_branch(self, plugin_name):
        """
        Find the name of the currently checked out branch in the git repository
        of the given Vim plug-in.
        """
        output = run('git', 'symbolic-ref', 'HEAD',
                     cwd=self.plugins[plugin_name]['directory'],
                     capture=True)
        tokens = output.split('/')
        branch_name = tokens[-1]
        self.logger.verbose("Current branch: %s", branch_name)
        return branch_name

    def find_releases(self, plugin_name):
        """
        Find all tags in the git repository of the given Vim plug-in.
        """
        directory = self.plugins[plugin_name]['directory']
        return run('git', 'tag', cwd=directory, capture=True).split()

    def find_uncommitted_changes(self, plugin_name):
        """
        Find the uncommitted changes (if any) in the git repository of the
        given Vim plug-in.
        """
        changed_files = []
        directory = self.plugins[plugin_name]['directory']
        self.logger.verbose("Looking for uncommitted changes in git repository: %s", directory)
        output = run('git', 'status', '--porcelain', '--untracked-files=no', cwd=directory, capture=True)
        for line in output.splitlines():
            status, filename = line.split(None, 1)
            # Deal with renamed files.
            names = filename.split(' -> ', 1)
            if len(names) == 2:
                filename = names[1]
            changed_files.append(filename)
        return sorted(changed_files)

    def get_committed_contents(self, plugin_name, filename, revision='HEAD'):
        """
        Get the last committed contents of a file.
        """
        directory = self.plugins[plugin_name]['directory']
        filename = os.path.relpath(os.path.abspath(filename), os.path.abspath(directory))
        try:
            return run('git', 'show', '%s:%s' % (revision, filename), cwd=directory, capture=True, silent=True)
        except ExternalCommandFailed:
            return ''

    def get_staged_contents(self, plugin_name, filename):
        """
        Get the staged contents of a file.
        """
        return self.get_committed_contents(plugin_name, filename, revision='')

    def find_version_in_repository(self, plugin_name, branch_name='master'):
        """
        Find the version of a Vim plug-in that is the highest version number
        that has been committed to the local git repository of the plug-in (the
        version number is embedded as a string in the main auto-load script of
        the plug-in).
        """
        # Find the auto-load script.
        autoload_script = self.plugins[plugin_name]['autoload-script']
        # Find the name of the variable that should contain the version number.
        autoload_path = re.sub(r'^autoload/(.+?)\.vim$', r'\1', autoload_script)
        version_definition = 'let g:%s#version' % autoload_path.replace('/', '#')
        self.logger.debug("Finding local committed version by scanning %s for %r ..", autoload_script, version_definition)
        # Ignore uncommitted changes in the auto-load script.
        script_contents = self.get_committed_contents(plugin_name, autoload_script, revision=branch_name)
        # Look for the version definition.
        for line in script_contents.splitlines():
            if line.startswith(version_definition):
                tokens = line.split('=', 1)
                last_token = tokens[-1].strip()
                version_string = last_token.strip('\'"')
                self.logger.info("Found last committed version: %s", version_string)
                return version_string
        msg = "Failed to determine last committed version of %s!"
        raise Exception, msg % plugin_name

class ExternalCommandFailed(Exception):

    """
    Exception used to signal that an external command exited with a nonzero
    return code.
    """

    def __init__(self, msg, command):
        super(ExternalCommandFailed, self).__init__(msg)
        self.command = command

# TODO Merge GitVFS into vcs-repo-mgr? (don't forget about get_committed_contents() and get_staged_contents())

class GitVFS(object):

    """
    Virtual file system interface which looks at the git HEAD of the master
    branch in the given directory.
    """

    def __init__(self, root):
        self.root = os.path.abspath(root)

    def __str__(self):
        return "git master branch in %s" % self.root

    def list(self):
        return run('git', 'ls-files', '--full-name', cwd=self.root, capture=True).splitlines()

    def read(self, filename):
        return run('git', 'show', ':%s' % filename, cwd=self.root, capture=True)

# FIXME Switch to executor.execute() once vim-plugin-manager is a proper Python package.

def run(*args, **kw):
    """
    Run an external process, make sure it exited with a zero return code and
    return the standard output stripped from leading/trailing whitespace.
    """
    # Prepare keyword arguments for subprocess.Popen().
    context = dict(cwd=os.path.abspath(kw.get('cwd', '.')))
    if 'input' in kw:
        context['stdin'] = subprocess.PIPE
    if kw.get('capture', False):
        context['stdout'] = subprocess.PIPE
    if kw.get('silent', False):
        if 'stdout' not in context:
            context['stdout'] = subprocess.PIPE
        context['stderr'] = subprocess.PIPE
    process = subprocess.Popen(args, **context)
    stdout, stderr = process.communicate(input=kw.get('input', None))
    if kw.get('check', True) and process.returncode != 0:
        msg = "External command %r exited with code %i (working directory: %s)"
        raise ExternalCommandFailed(msg % (args, process.returncode, context['cwd']), args)
    if hasattr(stdout, 'strip'):
        return stdout.strip()

def cp1252_to_utf8(text):
    """
    Vim Online expects change logs encoded in CP-1252, however everywhere else
    I want UTF-8 (e.g. on the console and in the log file).
    """
    return text.decode('windows-1252').encode('utf-8')

def compact(text, **kw):
    """
    Compact whitespace in a string and format any keyword arguments into the
    resulting string.

    :param text: The text to compact (a string).
    :param kw: Any keyword arguments to apply using :py:func:`str.format()`.
    :returns: The compacted, formatted string.
    """
    return ' '.join(text.split()).format(**kw)

if __name__ == '__main__':
    main()

# vim: ts=4 sw=4 et
