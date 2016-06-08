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

from oslo_config import cfg
from oslo_context import context
from oslo_log import log

from ceilometer import dispatcher
from ceilometer import messaging
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


class RpcDispatcherProxy(object):
    def __init__(self, topic, version):
        transport = messaging.get_transport(
            url=CONF.dispatcher_rpc.transport_url)
        self.spool_size = CONF.dispatcher_rpc.spool_size
        self.queue = Queue.Queue(self.spool_size * 10)

        self.client = messaging.get_rpc_client(
            transport, topic=topic, version=version)
        LOG.debug("Spool size: %s" % self.spool_size)

    def send_meters(self, meters):
        overflow = False
        for meter in meters:
            self._maybe_flush()
            try:
                self.queue.put_nowait(meter)
            except Queue.Full:
                overflow = True
        if overflow:
            LOG.warning('Failed to record metering data: '
                        'RPC meter spool full.')

    def _maybe_flush(self):
        if self.queue.qsize() >= self.spool_size:
            self._flush()

    def _flush(self):
        meters = []
        while len(meters) < self.spool_size:
            try:
                meters.append(self.queue.get_nowait())
            except Queue.Empty:
                break

        LOG.debug("Forwarding %s meters" % len(meters))
        ctxt = context.get_admin_context()
        self.client.cast(ctxt, 'record_metering_data', data=meters)


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

    def record_metering_data(self, data):
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
                    self.conf.publisher.telemetry_secret):
                meters_to_forward.append(meter)
            else:
                LOG.warning(
                    'message signature invalid, discarding message: %r',
                    meter)
        try:
            if meters_to_forward:
                self.rpc_proxy.send_meters(meters_to_forward)
        except Exception as err:
            LOG.error('Failed to record metering data: %s', err)
            LOG.exception(err)

    def record_events(self, events):
        pass
