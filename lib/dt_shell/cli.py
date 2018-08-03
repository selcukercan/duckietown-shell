# -*- coding: utf-8 -*-
from __future__ import print_function

import glob
import json
import os
from cmd import Cmd
from os import makedirs, remove, utime
from os.path import basename, isfile, isdir, exists

from git import Repo
from git.exc import NoSuchPathError, InvalidGitRepositoryError

# sys.path.insert(0, dirname(__file__) + "/lib/")
# sys.path.insert(0, dirname(__file__) + "/commands/lib/")
from .constants import DTShellConstants
from .dt_command_abs import DTCommandAbs
from .dt_command_placeholder import DTCommandPlaceholder

DEBUG = False


class DTShell(Cmd, object):
    NAME = 'Duckietown Shell'
    VERSION = '0.1 (beta)'
    prompt = 'dt> '
    config = {}
    commands = {}
    core_commands = ['commands', 'install', 'uninstall', 'update', 'version', 'exit', 'help']

    def __init__(self):
        self.intro = "" \
                     "Welcome to the Duckietown shell.\n" \
                     "Version: %s\n\n" \
                     "Type help or ? to list commands.\n" % self.VERSION
        self.config_path = os.path.expanduser(DTShellConstants.ROOT)
        self.config_file = os.path.join(self.config_path, 'config')
        self.commands_path = os.path.join(self.config_path, 'commands')

        # create config if it does not exist
        if not exists(self.config_path):
            makedirs(self.config_path, mode=0755)
        if not exists(self.config_file):
            self.save_config()
        # load config
        self.load_config()
        # init commands
        if exists(self.commands_path) and isfile(self.commands_path):
            remove(self.commands_path)
        if not exists(self.commands_path):
            if not self._init_commands():
                exit()
        # discover commands
        self.reload_commands()
        # call super constructor
        super(DTShell, self).__init__()
        # remove the char `-` from the list of word separators, this allows us to suggest flags
        if self.use_rawinput and self.completekey:
            import readline
            readline.set_completer_delims(readline.get_completer_delims().replace('-', '', 1))

    def postcmd(self, stop, line):
        if len(line.strip()) > 0:
            print('')

    def emptyline(self):
        pass

    def complete(self, text, state):
        res = super(DTShell, self).complete(text, state)
        if res is not None: res += ' '
        return res

    def get_version(self):
        return self.VERSION

    def load_config(self):
        with open(self.config_file, 'r') as fp:
            self.config = json.load(fp)

    def save_config(self):
        with open(self.config_file, 'w') as fp:
            json.dump(self.config, fp)

    def reload_commands(self):
        # get installed commands
        installed_commands = self.commands.keys()
        for command in installed_commands:
            if (hasattr(DTShell, 'do_' + command)): delattr(DTShell, 'do_' + command)
            if (hasattr(DTShell, 'complete_' + command)): delattr(DTShell, 'complete_' + command)
            if (hasattr(DTShell, 'help_' + command)): delattr(DTShell, 'help_' + command)
        # re-install commands
        self.commands = self._get_commands(self.commands_path)
        if self.commands is None:
            print('No commands found.')
            self.commands = {}
        # load commands
        for cmd, subcmds in self.commands.items():
            self._load_commands('commands.', cmd, subcmds, 0)

    def enable_command(self, command_name):
        if command_name in self.core_commands: return True
        # get list of all commands
        res = self._get_commands(self.commands_path, all=True)
        present = res.keys() if res is not None else []
        # enable if possible
        if command_name in present:
            flag_file = '%s%s/installed.flag' % (self.commands_path, command_name)
            self._touch(flag_file)
        return True

    def disable_command(self, command_name):
        if command_name in self.core_commands: return False
        # get list of all commands
        res = self._get_commands(self.commands_path, all=True)
        present = res.keys() if res is not None else []
        # enable if possible
        if command_name in present:
            flag_file = '%s%s/installed.flag' % (self.commands_path, command_name)
            remove(flag_file)
        return True

    def _init_commands(self):
        print('Downloading commands in %s ...' % self.commands_path)
        # create commands repo
        commands_repo = Repo.init(self.commands_path)
        # the repo now exists
        origin = commands_repo.create_remote('origin', DTShellConstants.commands_remote_url)
        # check existence of `origin`
        if (not origin.exists()):
            print('The commands repository %r cannot be found. Exiting.' % origin.urls)
            return False
        # pull data
        origin.fetch()
        # create local.master <-> remote.master
        commands_repo.create_head('master', origin.refs.master)
        commands_repo.heads.master.set_tracking_branch(origin.refs.master)
        # pull data
        res = origin.pull()
        # the repo is there and there is a `origin` remote, merge
        commands_repo.heads.master.checkout()
        return True

    def update_commands(self):
        # create commands repo
        commands_repo = None
        try:
            commands_repo = Repo(self.commands_path)
        except (NoSuchPathError, InvalidGitRepositoryError) as e:
            # the repo does not exist
            if not self._init_commands():
                return False
        # the repo exists
        print('Updating commands...', end='')
        origin = commands_repo.remote('origin')
        # check existence of `origin`
        if not origin.exists():
            print('The commands repository %r cannot be found. Exiting.' % origin.urls)
            return False
        res = origin.pull()
        # pull data from remote.master to local.master
        commands_repo.heads.master.checkout()
        print('OK')
        # update all submodules
        print('Updating libraries...', end='')
        commands_repo.submodule_update(recursive=True, to_latest_revision=False)

        # TODO: make sure this is not necessary
        # for submodule in commands_repo.submodules:
        #     submodule.update(recursive=True, to_latest_revision=False)

        # everything should be fine
        print('OK')
        return True

    def _get_commands(self, path, lvl=0, all_commands=False):
        entries = glob.glob(path + "/*")
        files = [basename(e) for e in entries if isfile(e)]
        dirs = [e for e in entries if isdir(e) and (lvl > 0 or basename(e) != 'lib')]
        # base case: empty dir
        if 'command.py' not in files and not dirs:
            return None
        if not all_commands and lvl == 1 and 'installed.flag' not in files:
            return None
        # check subcommands
        subcmds = {}
        for d in dirs:
            f = self._get_commands(d, lvl + 1, all_commands)
            if f is not None: subcmds[basename(d)] = f
        # return
        return subcmds

    def _load_class(self, name):
        if DEBUG: print('DEBUG:: Loading %s' % name)
        components = name.split('.')
        mod = __import__(components[0])
        for comp in components[1:]:
            mod = getattr(mod, comp)
        return mod

    def _load_commands(self, package, command, sub_commands, lvl):
        # load command
        klass = None
        error_loading = False
        try:
            klass = self._load_class(package + command + '.command.DTCommand')
        except AttributeError:
            error_loading = True
        # handle loading error and wrong class
        if error_loading:
            klass = DTCommandPlaceholder()
            if DEBUG:
                print('ERROR while loading the command `%s`' % (package + command + '.command.DTCommand',))
        if not issubclass(klass.__class__, DTCommandAbs.__class__):
            klass = DTCommandPlaceholder()
            if DEBUG:
                print('Command `%s` not found' % (package + command + '.command.DTCommand',))
        # initialize list of subcommands
        klass.name = command
        klass.level = lvl
        klass.commands = {}
        # attach first-level commands to the shell
        if lvl == 0:
            do_command = getattr(klass, 'do_command')
            complete_command = getattr(klass, 'complete_command')
            help_command = getattr(klass, 'help_command')
            # wrap [klass, function] around a lambda function
            do_command_lam = lambda s, w: do_command(klass, s, w)
            complete_command_lam = lambda s, w, l, i, e: complete_command(klass, s, w, l, i, e)
            help_command_lam = lambda s: help_command(klass, s)
            # add functions do_* and complete_* to the shell
            setattr(DTShell, 'do_' + command, do_command_lam)
            setattr(DTShell, 'complete_' + command, complete_command_lam)
            setattr(DTShell, 'help_' + command, help_command_lam)
        # stop recursion if there is no subcommand
        if sub_commands is None: return
        # load sub-commands
        for cmd, subcmds in sub_commands.items():
            if DEBUG: print('DEBUG:: Loading %s' % package + command + '.*')
            kl = self._load_commands(package + command + '.', cmd, subcmds, lvl + 1)
            if kl is not None: klass.commands[cmd] = kl
        # return class for this command
        return klass

    def _touch(self, path):
        with open(path, 'a'):
            utime(path, None)
