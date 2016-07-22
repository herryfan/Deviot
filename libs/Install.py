#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import absolute_import
from __future__ import print_function
from __future__ import division
from __future__ import unicode_literals

import os
import time
import json
import datetime
import threading
import tempfile
import sublime
import subprocess
from shutil import rmtree
from re import match, sub
from urllib.request import Request
from urllib.request import urlopen
from collections import OrderedDict

from . import Paths
from . import Tools
from . import Messages
from .I18n import I18n
from . import __version__ as version
from .Preferences import Preferences
from .Progress import ThreadProgress
from .checksumdir import dirhash

_ = I18n().translate


class PioInstall(object):
    '''Handles installing and updating process

    Handle the installation and update platformio
    to stable and developer version
    '''

    def __init__(self, window=False, feedback=False):
        self.Preferences = Preferences()
        self.base_dir = Paths.getDeviotUserPath()
        self.env_dir = Paths.getEnvDir()
        self.env_bin_dir = Paths.getEnvBinDir()
        self.cache_dir = Paths.getCacheDir()
        self.env_file = Paths.getEnvFile()
        self.pio_current_ver = Preferences().get('pio_version', 0)
        self.feedback = feedback
        self.cached_file = False
        self.pio_version = None
        self.pio_cloud_ver = None

        # console
        if(not window):
            window = sublime.active_window()
        console = Messages.Console(window)

        # Queue for the user console
        self.message_queue = Messages.MessageQueue(console)

        if(not self.pio_current_ver):
            self.message_queue.startPrint()

        if(self.feedback):
            self.message_queue.startPrint()
            self.message_queue.put("_deviot_{0}", version)

    def checkPio(self):
        thread = threading.Thread(target=self.threadcheckPio)
        thread.start()
        ThreadProgress(thread, _('processing'), _('done'))

    def threadcheckPio(self):
        '''Check PlatformIO

        Check if platformIO is currently installed or if a
        new version is available

        Keyword Arguments:
            feedback {bool} -- avoids any message in console (default: {False})
        '''
        self.headers = Tools.getHeaders()

        if(self.pio_current_ver):
            # Check main menu
            updt_menu = self.Preferences.get('updt_menu', False)
            if(updt_menu):
                from .PlatformioCLI import generateFiles
                generateFiles()
                Tools.updateMenuLibs()
                self.Preferences.set('updt_menu', False)

            # Check library folder
            library_hash = self.Preferences.get('library_hash', False)
            current_hash = dirhash(Paths.getPioLibrary())

            if(not library_hash or library_hash != current_hash):
                Tools.updateMenuLibs()
                self.Preferences.set('library_hash', current_hash)

            # check update once each five
            date_now = datetime.datetime.now()
            date_update = self.Preferences.get('check_update', False)

            # compare the dates for check updates
            try:
                date_update = datetime.datetime.strptime(
                    date_update, '%Y-%m-%d %H:%M:%S.%f')

                if(not self.feedback and date_now < date_update):
                    return
            except:
                pass

            # saves the date in the preferences for next check
            if(not date_update or date_now > date_update):
                date_update = datetime.datetime.now() + datetime.timedelta(5, 0)
                self.Preferences.set('check_update', str(date_update))

        # check platformio
        if(sublime.platform() == 'osx'):
            executable = os.path.join(self.env_bin_dir, 'python')
            cmd = ['"%s"' % (executable), '-m', 'platformio', '--version']
        else:
            executable = os.path.join(self.env_bin_dir, 'pio')
            cmd = ['"%s"' % (executable), '--version']
        out = self.runCommand(cmd)

        # try to get the current version installed
        try:
            self.pio_version = sub(r'\D', '', out[1])
        except:
            self.pio_version = 0

        if(out[0] == 0):
            url = 'https://pypi.python.org/pypi/platformio/json'
            req = Request(url, headers=self.headers)
            response = urlopen(req)
            list = json.loads(response.read().decode())

            self.pio_cloud_ver = list['info']['version']

            # Show a message if the last version is installed
            if(int(self.pio_version) == int(sub(r'\D', '', self.pio_cloud_ver)) and
               not self.pio_current_ver):

                self.Preferences.set('pio_version', self.pio_version)
                self.message_queue.put("deviot_setup{0}", version)
                current_time = time.strftime('%H:%M:%S')
                self.message_queue.put("pio_is_installed{0}", current_time)
                self.endSetup()
                return

            # update Pio
            self.update()
        else:
            self.install()

    def install(self):
        '''Install Pio in virtualenv

        Check if Pio is in the system if it don't, downloads the virtualenv
        script and install platformIO on it. The state of the installation
        is displayed on the console
        '''

        # defining default env paths
        os.environ['PATH'] = self.getEnvPaths()

        # checking python
        cmd = ['python', '--version']
        out = self.runCommand(cmd)

        py_version = sub(r'\D', '', out[1])

        # show error and link to download
        if(out[0] > 0 or int(py_version[0]) == 3):
            current_time = time.strftime('%H:%M:%S')
            go_to = sublime.ok_cancel_dialog(
                _("deviot_need_python"), _("button_download_python"))
            if(go_to):
                sublime.run_command(
                    'open_url', {'url': 'https://www.python.org/downloads/'})
            return

        # pio not installe
        self.message_queue.put("deviot_setup{0}", version)
        current_time = time.strftime('%H:%M:%S')
        self.message_queue.put("pio_isn_installed{0}", current_time)

        # check if virtualenv file is cached
        if(os.path.exists(self.env_file)):
            self.cached_file = True

        # download virtualenv
        if(not self.cached_file):
            current_time = time.strftime('%H:%M:%S')
            self.message_queue.put("downloading_files{0}", current_time)

            url_file = 'https://pypi.python.org/packages/source/v/virtualenv/virtualenv-14.0.1.tar.gz'

            try:
                file_request = Request(url_file, headers=self.headers)
                file_open = urlopen(file_request)
                file = file_open.read()
            except:
                current_time = time.strftime('%H:%M:%S')
                self.message_queue.put(
                    "error_downloading_files{0}", current_time)
                print("There was an error downloading virtualenv")
                return
            # save file
            try:
                output = open(self.env_file, 'wb')
                output.write(bytearray(file))
                output.close()
            except:
                current_time = time.strftime('%H:%M:%S')
                self.message_queue.put(
                    "error_saving_files{0}", current_time)
                print("There was an error saving the virtualenv file")
                return

        # extract file
        current_time = time.strftime('%H:%M:%S')
        self.message_queue.put("extracting_files{0}", current_time)
        tmp = tempfile.mkdtemp()
        Tools.extractTar(self.env_file, tmp)

        # install virtualenv in a temp dir
        current_time = time.strftime('%H:%M:%S')
        self.message_queue.put("installing_pio{0}", current_time)

        temp_env = os.path.join(tmp, 'env-root')
        cwd = os.path.join(tmp, 'virtualenv-14.0.1')
        cmd = ['python', 'setup.py', 'install', '--root', temp_env]
        out = self.runCommand(cmd, cwd)

        py_version = sub(r'\D', '', out[1])

        # error
        if(out[0] > 0 or int(py_version) == 300):

            current_time = time.strftime('%H:%M:%S')
            self.message_queue.put(
                "error_installing_env_{0}", current_time)
            return

        # make vitualenv
        for root, dirs, files in os.walk(tmp):
            for file in files:
                if(file == 'virtualenv.py'):
                    cwd = root

        if(os.path.exists(cwd)):
            cmd = ['python', 'virtualenv.py', '"%s"' % (self.env_dir)]
            out = self.runCommand(cmd, cwd)

            # error
            if(out[0] > 0):
                current_time = time.strftime('%H:%M:%S')
                self.message_queue.put(
                    "error_making_env_{0}", current_time)
                return

        # remove temp dir
        rmtree(tmp)

        # Install pio
        if(sublime.platform() == 'osx'):
            executable = os.path.join(self.env_bin_dir, 'python')
            cmd = ['"%s"' % (executable), '-m', 'pip',
                   'install', '-U', 'platformio']
        else:
            executable = os.path.join(self.env_bin_dir, 'pip')
            cmd = ['"%s"' % (executable), 'install', '-U', 'platformio']
        out = self.runCommand(cmd)

        # Error
        if(out[0] > 0):
            current_time = time.strftime('%H:%M:%S')
            self.message_queue.put(
                "error_installing_pio_{0}", current_time)
            return

        self.endSetup()

        current_time = time.strftime('%H:%M:%S')
        self.message_queue.put("setup_finished{0}", current_time)

    def update(self):
        '''Update PlatformIO

        Check if a new version of platformIO was released and update it
        it is necessary.
        '''
        if(self.feedback):
            self.message_queue.put('checking_pio_updates')

        # check version installed and last released
        if(int(sub(r'\D', '', self.pio_cloud_ver)) != int(sub(r'\D', '', str(self.pio_current_ver)))):
            update = True
            if(not self.feedback):
                # Display a pop up window if a new version is available
                update = sublime.ok_cancel_dialog(_('new_pio_update{0}{1}',
                                                    self.pio_cloud_ver,
                                                    self.pio_current_ver),
                                                  _('update_button'))

            if(update):
                # try to update
                if(sublime.platform() == 'osx'):
                    executable = os.path.join(self.env_bin_dir, 'python')
                    cmd = ['"%s"' % (executable), '-m', 'pip',
                           'install', '-U', 'platformio']
                else:
                    executable = os.path.join(self.env_bin_dir, 'pip')
                    cmd = ['"%s"' % (executable), 'install',
                           '-U', 'platformio']
                out = self.runCommand(cmd)

                # error updating
                if(out[0] > 0):
                    self.message_queue.put('error_pio_updates')
                    return

                # get version
                if(sublime.platform() == 'osx'):
                    executable = os.path.join(self.env_bin_dir, 'python')
                    cmd = ['"%s"' % (executable), '-m',
                           'platformio', '--version']
                else:
                    executable = os.path.join(self.env_bin_dir, 'pio')
                    cmd = ['"%s"' % (executable), '--version']
                out = self.runCommand(cmd)

                pio_new_ver = match(r"\w+\W \w+ (.+)", out[1]).group(1)

                # pio update installed
                self.message_queue.put(
                    'pio_new_updated_installed{0}', pio_new_ver)
                self.Preferences.set('pio_version', pio_new_ver)
                return
        else:
            # creating files (menu, completions, syntax)
            Tools.updateMenuLibs()
            if(self.feedback):
                self.message_queue.put('pio_up_date{0}', self.pio_cloud_ver)
                self.Preferences.set('pio_version', self.pio_cloud_ver)
        return

    def getEnvPaths(self):
        '''Environment

        All the necessary environment paths are merged to run platformIO
        correctly

        Returns:
            [list] -- paths in a list
        '''
        # default paths
        default_paths = Tools.getDefaultPaths()
        system_paths = os.environ.get("PATH", "").split(os.path.pathsep)

        env_paths = []
        env_paths.extend(default_paths)
        env_paths.extend(system_paths)

        env_paths = list(OrderedDict.fromkeys(env_paths))
        env_paths = os.path.pathsep.join(env_paths)

        return env_paths

    def saveEnvPaths(self, new_path):
        '''Environment

        After install all the necessary dependencies to run the plugin,
        the environment paths are stored in the preferences file

        Arguments:
            new_path {[list]} -- list with extra paths to store
        '''
        env_paths = self.getEnvPaths().split(os.path.pathsep)

        paths = []
        paths.extend(new_path)
        paths.extend(env_paths)

        paths = list(OrderedDict.fromkeys(paths))
        paths = os.path.pathsep.join(paths)

        self.Preferences.set('env_path', paths)

    def endSetup(self):
        '''End Setup

        Ends the setup of the plugin generating menus and storing
        final settings in a file
        '''

        # save env paths
        env_path = [Paths.getEnvDir(), self.env_bin_dir]
        self.saveEnvPaths(env_path)

        # get pio version
        if(sublime.platform() == 'osx'):
            executable = os.path.join(self.env_bin_dir, 'python')
            cmd = ['"%s"' % (executable), '-m', 'platformio', '--version']
        else:
            executable = os.path.join(self.env_bin_dir, 'pio')
            cmd = ['"%s"' % (executable), '--version']
        out = self.runCommand(cmd)

        pio_version = match(r"\w+\W \w+ (.+)", out[1]).group(1)
        self.Preferences.set('pio_version', pio_version)

        # creating files (menu, completions, syntax)
        from .PlatformioCLI import PlatformioCLI, generateFiles
        PlatformioCLI(feedback=False, console=False).getAPIBoards()
        Tools.updateMenuLibs()
        generateFiles()

        self.Preferences.set('protected', True)
        self.Preferences.set('enable_menu', True)

    def developer(self):
        '''Develop Branch

        Install the develop branch of platformIO
        '''
        developer = self.Preferences.get('developer', False)

        # Uninstall current version
        if(sublime.platform() == 'osx'):
            executable = os.path.join(self.env_bin_dir, 'python')
            cmd = ['"%s"' % (executable), '-m', 'pip',
                   'uninstall', '--yes', 'platformio']
        else:
            executable = os.path.join(self.env_bin_dir, 'pip')
            cmd = ['"%s"' % (executable), 'uninstall', '--yes', 'platformio']
        current_time = time.strftime('%H:%M:%S')
        self.message_queue.put("uninstall_old_pio{0}", current_time)
        out = self.runCommand(cmd)

        if(not developer):
            # install developer version
            if(sublime.platform() == 'osx'):
                executable = os.path.join(self.env_bin_dir, 'python')
                cmd = ['"%s"' % (executable), '-m', 'pip',
                       'install', '-U', 'https://github.com/platformio/platformio/archive/develop.zip']
            else:
                executable = os.path.join(self.env_bin_dir, 'pip')
                cmd = ['"%s"' % (executable), 'install', '-U',
                       'https://github.com/platformio/platformio/archive/develop.zip']
            current_time = time.strftime('%H:%M:%S')
            self.message_queue.put("installing_dev_pio{0}", current_time)
            out = self.runCommand(cmd)

        else:
            # install stable version
            if(sublime.platform() == 'osx'):
                executable = os.path.join(self.env_bin_dir, 'python')
                cmd = ['"%s"' % (executable), '-m', 'pip',
                       'install', '-U', 'platformio']
            else:
                executable = os.path.join(self.env_bin_dir, 'pip')
                cmd = ['"%s"' % (executable), 'install', '-U', 'platformio']
            current_time = time.strftime('%H:%M:%S')
            self.message_queue.put("installing_stable_pio{0}", current_time)
            out = self.runCommand(cmd)
        # show status in deviot console
        if(out[0] > 0):
            self.message_queue.put('error_pio_updates')
        else:
            # get pio version
            if(sublime.platform() == 'osx'):
                executable = os.path.join(self.env_bin_dir, 'python')
                cmd = ['"%s"' % (executable), '-m',
                       'platformio', '--version']
            else:
                executable = os.path.join(self.env_bin_dir, 'pio')
                cmd = ['"%s"' % (executable), '--version']
            out = self.runCommand(cmd)

            # Storing pio version and developer state
            pio_version = match(r"\w+\W \w+ (.+)", out[1]).group(1)
            self.Preferences.set('pio_version', pio_version)
            self.Preferences.set('developer', not developer)

            # updating status bar
            Tools.setStatus()
            current_time = time.strftime('%H:%M:%S')
        self.message_queue.put("setup_finished{0}", current_time)

    def runCommand(self, command, cwd=None):
        '''Commands

        Run all the commands to install the plugin

        Arguments:
            command {[list]} -- [list of commands]

        Keyword Arguments:
            cwd {[str]} -- [current working dir] (default: {None})

        Returns:
            [list] -- list[0]: return code list[1]: command output
        '''
        command.append("2>&1")
        command = ' '.join(command)
        process = subprocess.Popen(command, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, cwd=cwd,
                                   universal_newlines=True, shell=True)

        output = process.communicate()
        stdout = output[0]
        return_code = process.returncode

        if(return_code > 0):
            print(stdout)

        return (return_code, stdout)

    def openInThread(self, func, join=False):
        """
        Opens each action; build/upload/clean in a new thread

        Arguments: type {string} -- type of action.
                   Valid values: build/upload/clean
        """
        thread = threading.Thread(target=func)
        thread.start()
        if(join):
            thread.join()
        ThreadProgress(thread, _('processing'), _('done'))
