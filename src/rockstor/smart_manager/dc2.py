from gevent import monkey
monkey.patch_all()

import gevent
from socketio.server import SocketIOServer
from socketio import socketio_manage
from socketio.namespace import BaseNamespace
from socketio.mixins import BroadcastMixin
from django.conf import settings
from system.osi import (uptime, kernel_info)
from system.services import service_status
from cli.rest_util import api_call
import logging
logger = logging.getLogger(__name__)


class ServicesNamespace(BaseNamespace, BroadcastMixin):

    # Called before the recv_connect function
    def initialize(self):
        logger.debug('Services have been initialized')

    def recv_connect(self):
        logger.debug("Services has connected")
        self.emit('services:connected', {
            'key': 'services:connected', 'data': 'connected'
        })
        self.spawn(self.send_service_statuses)

    def recv_disconnect(self):
        logger.debug("Services have disconnected")

    def send_service_statuses(self):
        # Iterate through the collection and assign the values accordingly
        services = ('nfs', 'smb', 'ntpd', 'winbind', 'netatalk',
                    'snmpd', 'docker', 'smartd', 'replication',
                    'nis', 'ldap', 'sftp', 'data-collector', 'smartd',
                    'service-monitor', 'docker', 'task-scheduler')
        while True:
            data = {}
            for service in services:
                data[service] = {}
                output, error, return_code = service_status(service)
                if (return_code == 0):
                    data[service]['running'] = return_code
                else:
                    data[service]['running'] = return_code

            self.emit('services:get_services', {
                'data': data, 'key': 'services:get_services'
            })
            gevent.sleep(5)


class SysinfoNamespace(BaseNamespace, BroadcastMixin):
    start = False
    supported_kernel = settings.SUPPORTED_KERNEL_VERSION
    base_url = 'https://localhost/api'

    # Called before the connection is established
    def initialize(self):
        logger.debug("Sysinfo has been initialized")

    # This function is run once on every connection
    def recv_connect(self):
        logger.debug("Sysinfo has connected")
        self.emit("sysinfo:sysinfo", {
            "key": "sysinfo:connected", "data": "connected"
        })
        self.start = True
        gevent.spawn(self.send_uptime)
        gevent.spawn(self.send_kernel_info)
        gevent.spawn(self.update_rockons)
        gevent.spawn(self.refresh_disks)
        gevent.spawn(self.refresh_pools)
        gevent.spawn(self.refresh_shares)

    # Run on every disconnect
    def recv_disconnect(self):
        logger.debug("Sysinfo has disconnected")
        self.start = False

    def send_uptime(self):
        # Seems redundant
        while self.start:
            self.emit('sysinfo:uptime', {
                'data': uptime(), 'key': 'sysinfo:uptime'
            })
            gevent.sleep(30)

    def send_kernel_info(self):
            try:
                self.emit('sysinfo:kernel_info', {
                    'data': kernel_info(self.supported_kernel),
                    'key': 'sysinfo:kernel_info'
                })
            except Exception as e:
                logger.debug('kernel error')
                # Emit an event to the front end to capture error report
                self.emit('sysinfo:kernel_error', {
                    'data': str(e),
                    'key': 'sysinfo:kernel_error'
                })
                self.error('unsupported_kernel', str(e))

    def update_rockons(self):
        try:
            url = '%s/rockons/update' % self.base_url
            api_call(url, data=None, calltype='post', save_error=False)
            logger.debug('Updated Rock-on metadata')
        except Exception, e:
            logger.debug('failed to update Rock-on metadata. low-level '
                         'exception: %s' % e.__str__())

    def refresh_disks(self):
        try:
            url = '%s/disks/scan' % self.base_url
            api_call(url, data=None, calltype='post', save_error=False)
            logger.debug('Disk scan finished')
        except Exception, e:
            logger.error('failed to perform disk scan. low-level exception: '
                         '%s' % e.__str__())

    def refresh_pools(self):
        try:
            url = '%s/commands/refresh-pool-state' % self.base_url
            api_call(url, data=None, calltype='post', save_error=False)
            logger.debug('Pool state refreshed successfully.')
        except Exception, e:
            logger.error('failed to refresh pool state. low-level exception: '
                         '%s' % e.__str__())

    def refresh_shares(self):
        try:
            url = '%s/commands/refresh-share-state' % self.base_url
            api_call(url, data=None, calltype='post', save_error=False)
            logger.debug('Share state refreshed successfully.')
        except Exception, e:
            logger.error('failed to refresh share state. low-level '
                         'exception: %s' % e.__str__())

class Application(object):
    def __init__(self):
        self.buffer = []

    def __call__(self, environ, start_response):
        path = environ['PATH_INFO'].strip('/') or 'index.html'

        if path.startswith('/static') or path == 'index.html':
            try:
                data = open(path).read()
            except Exception:
                return not_found(start_response)

            if path.endswith(".js"):
                content_type = "text/javascript"
            elif path.endswith(".css"):
                content_type = "text/css"
            elif path.endswith(".swf"):
                content_type = "application/x-shockwave-flash"
            else:
                content_type = "text/html"

            start_response('200 OK', [('Content-Type', content_type)])
            return [data]
        if path.startswith("socket.io"):
            socketio_manage(environ, {'/services': ServicesNamespace,
                                      '/sysinfo': SysinfoNamespace})


def not_found(start_response):
    start_response('404 Not Found', [])
    return ['<h1>Not found</h1>']


def main():
    logger.debug('Listening on port http://127.0.0.1:8080 and on port 10843 (flash policy server)')
    SocketIOServer(('127.0.0.1', 8001), Application(),
            resource="socket.io", policy_server=True).serve_forever()
