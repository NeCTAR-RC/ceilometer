# Copyright 2017 NeCTAR
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

import time
import uuid

import cotyledon
from oslo_log import log
import oslo_messaging

from ceilometer import messaging
from ceilometer import utils

LOG = log.getLogger(__name__)


""" If more complexity is needed
from ceilometer.i18n import _
from ceilometer.agent import plugin_base
from ceilometer import pipeline

class PublishContext(object):
    def __enter__(self):
        def p(data):
            pass
        return p

    def __exit__(self, exc_type, exc_value, traceback):
        pass

class NotificationManager(pipeline.ConfigManagerBase):
    def publisher(self):
        return PublishContext()

class NotificationProcess(plugin_base.NotificationBase):
    event_types = []

    def __init__(self, manager, topic):
        super(NotificationProcess, self).__init__(manager)
        self.topic = topic

    def get_targets(self, conf):
        return [
            oslo_messaging.Target(
                topic=self.topic, exchange=conf.ceilometer_control_exchange)
            ]

"""


class NotificationEndpoint(object):
    def sample(self, messages):
        for m in messages:
            self.process_notification(m)

    def process_notification(self, message):
        try:
            _process_message(message)
        except Exception:
            LOG.exception("Failed to handle nessage, re-queuing it.")
            return oslo_messaging.NotificationResult.REQUEUE

    def _process_message(self, message):
        # XXX this is where some processing will take place,
        # this is just a placeholder
        pipe = message["event_type"]
        LOG.info(pipe)
        payload = message["payload"]
        for ev in payload:
            """
            from oslo_utils import timeutils

            message_id = ev['message_id']
            event_type = ev['event_type']
            generated = timeutils.normalize_time(
                timeutils.parse_isotime(ev['generated']))
            for name, dtype, value in ev['traits']:
                pass
            """
            LOG.info(ev)


class QueueProcessService(cotyledon.Service):
    listener = None

    def __init__(self, worker_id, conf, topic, coordination_id=None):
        super(QueueProcessService, self).__init__(worker_id)
        self.startup_delay = worker_id
        self.conf = conf
        self.topic = topic

        # XXX uuid4().bytes ought to work, but it requires ascii for now
        self.coordination_id = (coordination_id or
                                str(uuid.uuid4()).encode('ascii'))

    def run(self):
        # Delay startup so workers are jittered
        time.sleep(self.startup_delay)

        """ More complexity scenario
        handler = NotificationProcess(
            NotificationManager(self.conf), self.topic)
        endpoints = [handler]
        targets = handler.get_targets(self.conf)
        """

        endpoints = [NotificationEndpoint()]
        targets = [
            oslo_messaging.Target(
                topic=self.topic,
                exchange=self.conf.ceilometer_control_exchange
                )
            ]
        transport = messaging.get_transport(self.conf)

        super(QueueProcessService, self).run()

        self.listener = messaging.get_batch_notification_listener(
            transport, targets, endpoints)
        self.listener.start()

    def terminate(self):
        if self.listener:
            utils.kill_listeners([self.listener])
        super(QueueProcessService, self).terminate()
