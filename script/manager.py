#!/usr/bin/env python
# -*- coding: utf-8 -*-

#   Copyright (c) 2010-2016, MIT Probabilistic Computing Project
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

import os
import re
import subprocess
import warnings

import notebook.auth

from iventure.utils_unix import unix_port_active
from iventure.utils_unix import unix_user_addgroup
from iventure.utils_unix import unix_user_create
from iventure.utils_unix import unix_user_delete
from iventure.utils_unix import unix_user_exists
from iventure.utils_unix import unix_user_id


NGINX_CONFIG_DIR = '/etc/nginx/jupyter'


def nginx_config_create(username, port):
    if not unix_user_exists(username):
        raise ValueError('No such user: %s' % (username,))
    if not os.path.exists(NGINX_CONFIG_DIR):
        raise ValueError('NGINX does not have a config directory.')

    config = os.path.join(NGINX_CONFIG_DIR, '%s.conf' % (username))
    if os.path.exists(config):
        raise ValueError('NGINX config already exists: %s' % (username,))

    # These are the lines which we need to write to
    # NGIN_CONFIG_DIR/username.conf create.
    lines = '''location /jupyter/%s/ {
        proxy_pass http://127.0.0.1:%d/jupyter/%s/;
        proxy_set_header Host $host;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        }''' % (username, port, username,)

    # Copy to a temp file.
    with open('/tmp/%s.conf' % (username,), 'w') as f:
        f.write(lines)

    # Copy the temp file to the target directory.
    process = subprocess.Popen(
        'sudo cp /tmp/%s.conf %s' % (username, NGINX_CONFIG_DIR),
        shell=True)
    process.wait()

    # Reload the nginx configuration to obtain the new .conf file.
    process = subprocess.Popen('sudo service nginx reload', shell=True)
    process.wait()


def nginx_config_delete(username):
    if not unix_user_exists(username):
        raise ValueError('No such user: %s' % (username,))
    if not os.path.exists(NGINX_CONFIG_DIR):
        raise ValueError('NGINX does not have a config directory.')

    config = os.path.join(NGINX_CONFIG_DIR, '%s.conf' % (username))
    if not os.path.exists(config):
        raise ValueError('NGINX config does not exist: %s' % (username,))

    process = subprocess.Popen('sudo rm -rf %s' % (config,), shell=True)
    process.wait()


def nginx_find_port(username):
    if not os.path.exists(NGINX_CONFIG_DIR):
        raise ValueError('NGINX does not have a config directory.')

    config = os.path.join(NGINX_CONFIG_DIR, '%s.conf' % (username))
    if not os.path.exists(config):
        raise ValueError('NGINX config does not exist: %s' % (username,))

    if not unix_user_exists(username):
        warnings.warn('Config file exists, but user does not: %s' % (username,))

    # The port is $1 on the line with the form
    #   proxy_pass http://127.0.0.1:$1/jupyter/$1/;
    with open(config, 'r') as f:
        lines = f.readlines()

    proxy_pass_lines = [
        line for line in lines
        if line.strip().startswith('proxy_pass')
    ]
    assert len(proxy_pass_lines) == 1

    proxy_pass_line = proxy_pass_lines[0].strip()
    match = re.search('127\.0\.0\.1:(.*)/jupyter', proxy_pass_line)

    if not (match and match.group(1)):
        raise ValueError('Faied to parse port from: %s' % (config,))

    port = int(match.group(1))
    return port


def jupyter_config_create(username, venv, port, prefix=None):
    if prefix and not str.startswith(username, prefix):
        raise ValueError(
            'Username must start with "%s": %s' % (prefix, username,))
    if not unix_user_exists(username):
        raise ValueError('No such user: %s' % (username,))

    # Retrieve a password for the jupyter server.
    passwd = notebook.auth.passwd()

    # Create a .jupyter/jupter_notebook_config.py file.
    process = subprocess.Popen(
        'sudo -iu %s sh -c "'
            ' . %s/bin/activate;'
            ' cd ~;'
            ' jupyter notebook --generate-config -y;'
            '"' % (username, venv),
        shell=True)
    process.wait()

    # Add lines to the configuration file.
    process = subprocess.Popen(
        'sudo -iu %s sh -c "'
            ' cd ~/.jupyter;'
            ' echo >> jupyter_notebook_config.py;'
            ' echo \# Configuration generated by iventure_manager >> jupyter_notebook_config.py;'
            ' echo \'c.NotebookApp.base_url = u\\"/jupyter/%s\\"\' >> jupyter_notebook_config.py;'
            ' echo \'c.NotebookApp.open_browser = False\' >> jupyter_notebook_config.py;'
            ' echo \'c.NotebookApp.port = %d\' >> jupyter_notebook_config.py;'
            ' echo \'c.NotebookApp.port_retries = 0\' >> jupyter_notebook_config.py;'
            ' echo \'c.NotebookApp.ip = u\\"127.0.0.1\\"\' >> jupyter_notebook_config.py;'
            ' echo \'c.NotebookApp.password = u\\"%s\\"\' >> jupyter_notebook_config.py;'
            '"' % (username, username, port, passwd,),
        shell=True)
    process.wait()


def jupyter_find_pid(username):
    if not unix_user_exists(username):
        raise ValueError('No such user: %s' % (username,))

    # Use netstat to find all the processes (`$9`) belonging to the `user_id`
    # listening `port`.
    process = subprocess.Popen(
        'sudo netstat -lnptue | '
            'awk \' ($4 ~ "127\\\.0\\\.0\\\.1") && ($7==%d)'
            '{split($9,pid,"/"); print pid[1]}\''
        % (unix_user_id(username),),
        shell=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    pid, _err = process.communicate()

    return int(str.strip(pid)) if pid else None


def jupyter_find_port(username):
    if not unix_user_exists(username):
        raise ValueError('No such user: %s' % (username,))

    # Use netstat to find all the processes (`$9`) belonging to the `user_id`
    # listening `port`.
    process = subprocess.Popen(
        'sudo netstat -lnptue | '
            'awk \' ($4 ~ "127\\\.0\\\.0\\\.1") && ($7==%d)'
            '{split($4,port,":"); print port[2]}\''
        % (unix_user_id(username),),
        shell=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    port, _err = process.communicate()

    return int(str.strip(port)) if port else None


def jupyter_server_start(username, venv):
    if not unix_user_exists(username):
        raise ValueError('No such user: %s' % (username,))

    # Only one server per `username` is allowed.
    pid = jupyter_find_pid(username)
    port = jupyter_find_port(username)
    if pid or port:
        raise ValueError(
            'User already %s has servers at (pid, port): %s, %s.'
            % (username, pid, port,))

    subprocess.Popen(
        'sudo -iu %s sh -c ". %s/bin/activate;'
        'cd ~; '
        'nohup jupyter notebook;"'
            % (username, venv),
        shell=True)

    import time; time.sleep(1)
    pid = jupyter_find_pid(username)
    port = jupyter_find_port(username)
    print 'Server running at pid, port: %d, %d.' % (pid, port)
    return pid, port


def jupyter_server_stop(username):
    if not unix_user_exists(username):
        raise ValueError('No such user: %s' % (username,))

    pid = jupyter_find_pid(username)
    port = jupyter_find_port(username)
    if pid is None or port is None:
        raise ValueError('No servers for user: %s.' % (username,))
    pgrp = os.getpgid(pid)
    subprocess.Popen('sudo kill -9 -%d' % (pgrp), shell=True)
    print 'Server killed at pid, port: %d, %d.' % (pid, port)
    return pid, port


class IVentureManager(object):
    '''IVentureManager is a simple command line utitly for:

        - Creating new UNIX users on a server to interact with iVenture.
        - Starting a Jupyter server for a user.
        - Terminating the Jupyter server for a user.
    '''


    # `dir_root` contains all the home directories for the created users.
    # `dir_venv` contains the python virtualenvironment shared by all the users.
    # `grp_unix` is the UNIX group to which all users belong.
    # `usr_prefix` is the prefix for users created by this manager.
    # `ports` is the filename for user and ports.
    # `start` is the first port number to start assigning.

    CONFIG = {
        'dir_root': os.path.join('/', 'scratch', 'pp_iventure'),
        'dir_venv': os.path.join('/', 'scratch', 'pp_iventure', '.pyenv2.7.6'),
        'grp_unix': 'pp_iventure',
        'usr_prefix': 'pp_',
        'start': 10000,
    }

    def __init__( self, dir_root=None, dir_venv=None, grp_unix=None,
            usr_prefix=None, start=None):
        if dir_root is None:
            dir_root = IVentureManager.CONFIG['dir_root']
        if dir_venv is None:
            dir_venv = IVentureManager.CONFIG['dir_venv']
        if grp_unix is None:
            grp_unix = IVentureManager.CONFIG['grp_unix']
        if usr_prefix is None:
            usr_prefix = IVentureManager.CONFIG['usr_prefix']
        if start is None:
            start = IVentureManager.CONFIG['start']

        self.dir_root = dir_root
        self.dir_venv = dir_venv
        self.grp_unix = grp_unix
        self.usr_prefix = usr_prefix
        self.start = start


    def server_restart(self, username):
        self.server_stop(username)
        self.server_start(username)

    def server_start(self, username):
        _pid, port = jupyter_server_start(username, self.dir_venv)
        assert port == self._user_lookup_port(username)


    def server_stop(self, username):
        _pid, port = jupyter_server_stop(username)
        assert port == self._user_lookup_port(username)


    def server_status(self, username):
        pid = jupyter_find_pid(username)
        if not pid:
            print 'No active servers for: %s' % (username,)
        else:
            port = self._user_lookup_port(username)
            print 'User %s has servers at (pid, port): %s, %s.'\
            % (username, pid, port,)


    def user_create(self, username):
        self._validate_username(username)

        if unix_user_exists(username):
            raise ValueError('Username already exists: %s' % (username,))

        # Create UNIX username, if does not exist, with home under dir_root.
        print 'Creating UNIX user: %s' % (username,)
        unix_user_create(username, os.path.join(self.dir_root, username))

        # Add user to shared `grp_unix`.
        print 'Adding user to group: %s' % (self.grp_unix,)
        unix_user_addgroup(username, self.grp_unix)

        # Retrieve the user port and write it to NGINX configuration.
        port = self._find_new_port()
        nginx_config_create(username, port)

        # Prepare the jupyter server configruation.
        print 'Creating a jupyter configuration file.'
        jupyter_config_create(username, self.dir_venv, port)


    def user_delete(self, username):
        self._validate_username(username)

        # Stop the server if it exists.
        pid = self.server_status(username)
        if pid:
            port = self._user_lookup_port(username)
            print 'Stopping server at (pid, port): %s, %s.' % (pid, port,)
            self.server_stop(username)

        # Remove the nginx config file.
        print 'Removing nginx configuration file.'
        nginx_config_delete(username)

        # Delete the user account from the system.
        unix_user_delete(username)
        print 'Removing user from system.'


    def _find_new_port(self):
        table = self._load_port_assignments()
        unavailable = table.values()
        for p in xrange(self.start, self.start + 500):
            if unix_port_active(p) or p in unavailable:
                continue
            return p
        raise ValueError('Failed to find a free port.')


    def _find_usernames(self):
        return [
            f.replace('.conf', '')
            for f in os.listdir(NGINX_CONFIG_DIR)
            if f.startswith(self.usr_prefix)
        ]


    def _load_port_assignments(self):
        usernames = self._find_usernames()
        ports = [nginx_find_port(username) for username in usernames]
        table = zip(usernames, ports)
        return dict(table)


    def _user_lookup_port(self, username):
        table = self._load_port_assignments()
        if username not in table:
            raise ValueError('No such user in ports: %s' % (username,))
        return table[username]


    def _validate_username(self, username):
        if not str.startswith(username, self.usr_prefix):
            raise ValueError(
                'Username must start with "%s": %s'
                % (self.usr_prefix, username,))


    def _verify_new_port(self, username, port):
        table = self._load_port_assignments()
        if username in table:
            raise ValueError('User already in ports: %s' % (username,))
        if port in table.values():
            raise ValueError('Port already in ports: %s' % (port))


if __name__ == '__main__':

    '''
    Usage:
        create a user:      ./manager.py user_create <username>
        delete a user:      ./manager.py user_delete <username>

        stop a server:      ./manager.py server_stop <username>
        start server:       ./manager.py server_start <username>
        restart server:     ./manager.py server_restart <username>
        check server:       ./manager.py server_status <username>
    '''

    import argparse
    parser = argparse.ArgumentParser()

    subparsers = parser.add_subparsers()

    parser_user_create = subparsers.add_parser('user_create')
    parser_user_create.add_argument('username', type=str)
    parser_user_create.set_defaults(
        func=lambda args: IVentureManager().user_create(args.username))

    parser_user_create = subparsers.add_parser('user_delete')
    parser_user_create.add_argument('username', type=str)
    parser_user_create.set_defaults(
        func=lambda args: IVentureManager().user_delete(args.username))

    parser_server_start = subparsers.add_parser('server_start')
    parser_server_start.add_argument('username', type=str)
    parser_server_start.set_defaults(
        func=lambda args: IVentureManager().server_start(args.username))

    parser_server_stop = subparsers.add_parser('server_stop')
    parser_server_stop.add_argument('username', type=str)
    parser_server_stop.set_defaults(
        func=lambda args: IVentureManager().server_stop(args.username))

    parser_server_status = subparsers.add_parser('server_status')
    parser_server_status.add_argument('username', type=str)
    parser_server_status.set_defaults(
        func=lambda args: IVentureManager().server_status(args.username))

    parser_restart = subparsers.add_parser('server_restart')
    parser_restart.add_argument('username', type=str)
    parser_restart.set_defaults(
        func=lambda args: IVentureManager().server_restart(args.username))

    args = parser.parse_args()
    args.func(args)