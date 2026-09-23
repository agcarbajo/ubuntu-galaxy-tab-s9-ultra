import argparse
import base64
import os
import shlex
import socket
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import paramiko


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--discover', nargs='+')
    parser.add_argument('--root', action='store_true')
    parser.add_argument('--upload', nargs=2, metavar=('LOCAL', 'REMOTE'))
    parser.add_argument('--download', nargs=2, metavar=('REMOTE', 'LOCAL'))
    parser.add_argument('--wait', type=int, default=0)
    parser.add_argument('command', nargs='?', default='true')
    args = parser.parse_args()
    key = paramiko.Ed25519Key(data=base64.b64decode(os.environ['TABLET_HOST_KEY']))

    def identify(host):
        try:
            with socket.create_connection((host, 22), timeout=2) as sock:
                transport = paramiko.Transport(sock)
                try:
                    transport.start_client(timeout=3)
                    if transport.get_remote_server_key() == key:
                        peer = sock.getpeername()
                        return peer[0] + (f'%{peer[3]}' if len(peer) == 4 and peer[3] else '')
                finally:
                    transport.close()
        except (OSError, paramiko.SSHException):
            return None

    if args.discover:
        with ThreadPoolExecutor(max_workers=12) as pool:
            for host in pool.map(identify, args.discover):
                if host:
                    print(host)
        return

    host = os.environ['TABLET_HOST']
    if not 0 <= args.wait <= 600:
        parser.error('--wait must be between 0 and 600 seconds')
    if args.wait:
        deadline = time.monotonic() + args.wait
        while not identify(host):
            if time.monotonic() >= deadline:
                raise SystemExit('Timed out waiting for the pinned tablet SSH identity')
            time.sleep(2)
    with paramiko.SSHClient() as client:
        client.get_host_keys().add(host, key.get_name(), key)
        client.connect(host, username=os.environ['TABLET_USER'],
                       password=os.environ['TABLET_PASSWORD'], timeout=10,
                       look_for_keys=False, allow_agent=False)
        if args.upload or args.download:
            with client.open_sftp() as sftp:
                if args.upload:
                    sftp.put(*args.upload)
                if args.download:
                    sftp.get(*args.download)
        command = args.command
        if args.root:
            command = "sudo -S -p '' -- sh -c " + shlex.quote(command)
        stdin, stdout, stderr = client.exec_command(command, timeout=180)
        if args.root:
            stdin.write(os.environ['TABLET_PASSWORD'] + '\n')
            stdin.flush()
        stdin.channel.shutdown_write()
        sys.stdout.buffer.write(stdout.read())
        sys.stderr.buffer.write(stderr.read())
        sys.exit(stdout.channel.recv_exit_status())


if __name__ == '__main__':
    main()
