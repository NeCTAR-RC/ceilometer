# -*- encoding: utf-8 -*-
#
# Copyright 2013 IBM Corp
#
# Author: Tong Li <litong01@us.ibm.com>
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import Queue
import urllib
import urlparse

from oslo.config import cfg

from ceilometer import dispatcher
from ceilometer.openstack.common import log
from ceilometer.openstack.common.rpc import proxy as rpc_proxy
from ceilometer.publisher import utils as publisher_utils


LOG = log.getLogger(__name__)


dispatcher_rpc_opts = [
    cfg.StrOpt('transport_url',
               default=None,
               help="URL of RPC server where metering messages will "
               "be dispatched."),
    cfg.IntOpt('spool_size',
               default=25,
               help="Number of meters to spool before sending a message."),
]

CONF = cfg.CONF
CONF.register_opts(dispatcher_rpc_opts, group='dispatcher_rpc')


class RpcDispatcherProxy(rpc_proxy.RpcProxy):
    def __init__(self, *args, **kwargs):
        super(RpcDispatcherProxy, self).__init__(*args, **kwargs)
        server_params = parse_transport_url(CONF.dispatcher_rpc.transport_url)
        self.server_params = dict(
            (k, v) for k, v in server_params.items() if v)
        self.spool_size = CONF.dispatcher_rpc.spool_size
        self.queue = Queue.Queue(self.spool_size * 10)
        LOG.debug("Spool size: %s" % self.spool_size)

    def send_meters(self, context, meters):
        overflow = False
        for meter in meters:
            self._maybe_flush(context)
            try:
                self.queue.put_nowait(meter)
            except Queue.Full:
                overflow = True
        if overflow:
            LOG.warning('Failed to record metering data: '
                        'RPC meter spool full.')

    def _maybe_flush(self, context):
        if self.queue.qsize() >= self.spool_size:
            self._flush(context)

    def _flush(self, context):
        meters = []
        while len(meters) < self.spool_size:
            try:
                meters.append(self.queue.get_nowait())
            except Queue.Empty:
                break

        LOG.debug("Forwarding %s meters" % len(meters))

        msg = {
            'method': 'record_metering_data',
            'version': '1.0',
            'args': {'data': meters},
        }
        self.cast_to_server(context, self.server_params, msg)


class RpcDispatcher(dispatcher.Base):
    '''Dispatcher class for forwarding metering data to an RPC server.

    The dispatcher class which forwards each meter to an RPC server configured
    in ceilometer configuration file.

    To enable this dispatcher, the following section needs to be present in
    ceilometer.conf file

    dispatchers = rpc
    '''
    BASE_RPC_API_VERSION = '1.0'

    def __init__(self, conf):
        super(RpcDispatcher, self).__init__(conf)
        topic = self.conf.publisher_rpc.metering_topic
        self.rpc_proxy = RpcDispatcherProxy(topic,
                                            self.BASE_RPC_API_VERSION)

    def record_metering_data(self, context, data):

        # We may have receive only one counter on the wire
        if not isinstance(data, list):
            data = [data]

        meters_to_forward = []
        for meter in data:
            LOG.debug('metering data %s for %s @ %s: %s',
                      meter['counter_name'],
                      meter['resource_id'],
                      meter.get('timestamp', 'NO TIMESTAMP'),
                      meter['counter_volume'])
            if publisher_utils.verify_signature(
                    meter,
                    self.conf.publisher.metering_secret):
                meters_to_forward.append(meter)
            else:
                LOG.warning(
                    'message signature invalid, discarding message: %r',
                    meter)
        try:
            if meters_to_forward:
                self.rpc_proxy.send_meters(context, meters_to_forward)
        except Exception as err:
            LOG.error('Failed to record metering data: %s', err)
            LOG.exception(err)

    def record_events(self, events):
        pass


def parse_transport_url(url):
    """
    Parse a transport URL.

    :param url: The transport URL.

    :returns: A dictionary of 5 elements: the "username", the
              "password", the "hostname", the "port" (as an integer),
              and the "virtual_host" for the requested transport.
    """

    # TODO(Vek): Use the actual Oslo code, once it lands in
    # oslo-incubator

    # First step is to parse the URL
    parsed = urlparse.urlparse(url or '')

    # Make sure we understand the scheme
    if parsed.scheme not in ('rabbit', 'qpid'):
        raise ValueError(_("Unable to handle transport URL scheme %s") %
                         parsed.scheme)

    # Make sure there's not a query string; that could identify
    # requirements we can't comply with (e.g., ssl), so reject it if
    # it's present
    if '?' in parsed.path or parsed.query:
        raise ValueError(_("Cannot comply with query string in transport URL"))

    # Extract the interesting information from the URL; this requires
    # dequoting values, and ensuring empty values become None
    username = urllib.unquote(parsed.username) if parsed.username else None
    password = urllib.unquote(parsed.password) if parsed.password else None
    virtual_host = urllib.unquote(parsed.path[1:]) or None

    # Now we have to extract the hostname and port; unfortunately,
    # urlparse in Python 2.6 doesn't understand IPv6 addresses
    hostname = parsed.hostname
    if hostname and hostname[0] == '[':
        # If '@' is present, rfind() finds its position; if it isn't,
        # rfind() returns -1.  Either way, adding 1 gives us the start
        # location of the host and port...
        host_start = parsed.netloc.rfind('@')
        netloc = parsed.netloc[host_start + 1:]

        # Find the closing ']' and extract the hostname
        host_end = netloc.find(']')
        if host_end < 0:
            # NOTE(Vek): Not translated so it's identical to what
            # Python 2.7's urlparse.urlparse() raises in this case
            raise ValueError("Invalid IPv6 URL")
        hostname = netloc[1:host_end]

        # Now we need the port; this is compliant with how urlparse
        # parses the port data
        port_text = netloc[host_end:]
        port = None
        if ':' in port_text:
            port = int(port_text.split(':', 1)[1])
    else:
        port = parsed.port

    # Now that we have what we need, return the information
    return {
        'username': username,
        'password': password,
        'hostname': hostname,
        'port': port,
        'virtual_host': virtual_host,
    }
