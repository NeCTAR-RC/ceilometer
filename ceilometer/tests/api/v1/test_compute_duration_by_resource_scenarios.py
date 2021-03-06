# -*- encoding: utf-8 -*-
#
# Copyright © 2012 New Dream Network, LLC (DreamHost)
#
# Author: Doug Hellmann <doug.hellmann@dreamhost.com>
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
"""Test listing raw events.
"""

import datetime

import mock
import testscenarios

from ceilometer.openstack.common import timeutils
from ceilometer.storage import models
from ceilometer.tests import api as tests_api
from ceilometer.tests import db as tests_db

load_tests = testscenarios.load_tests_apply_scenarios


class TestComputeDurationByResource(tests_api.TestBase,
                                    tests_db.MixinTestsWithBackendScenarios):

    def setUp(self):
        super(TestComputeDurationByResource, self).setUp()

        # Create events relative to the range and pretend
        # that the intervening events exist.

        self.early1 = datetime.datetime(2012, 8, 27, 7, 0)
        self.early2 = datetime.datetime(2012, 8, 27, 17, 0)

        self.start = datetime.datetime(2012, 8, 28, 0, 0)

        self.middle1 = datetime.datetime(2012, 8, 28, 8, 0)
        self.middle2 = datetime.datetime(2012, 8, 28, 18, 0)

        self.end = datetime.datetime(2012, 8, 28, 23, 59)

        self.late1 = datetime.datetime(2012, 8, 29, 9, 0)
        self.late2 = datetime.datetime(2012, 8, 29, 19, 0)

    def _patch_get_stats(self, start, end):
        statitics = models.Statistics(unit='',
                                      min=0, max=0, avg=0, sum=0, count=0,
                                      period=None,
                                      period_start=None,
                                      period_end=None,
                                      duration=end - start,
                                      duration_start=start,
                                      duration_end=end,
                                      groupby=None)
        return mock.patch.object(self.conn, 'get_meter_statistics',
                                 return_value=statitics)

    def _invoke_api(self):
        return self.get(
            '/resources/resource-id/meters/instance:m1.tiny/duration',
            start_timestamp=self.start.isoformat(),
            end_timestamp=self.end.isoformat(),
            search_offset=10,  # this value doesn't matter, db call is mocked
        )

    def test_before_range(self):
        with self._patch_get_stats(self.early1, self.early2):
            data = self._invoke_api()
        self.assertIsNone(data['start_timestamp'])
        self.assertIsNone(data['end_timestamp'])
        self.assertIsNone(data['duration'])

    def _assert_times_match(self, actual, expected):
        actual = timeutils.parse_isotime(actual).replace(tzinfo=None)
        self.assertEqual(expected, actual)

    def test_overlap_range_start(self):
        with self._patch_get_stats(self.early1, self.middle1):
            data = self._invoke_api()
        self._assert_times_match(data['start_timestamp'], self.start)
        self._assert_times_match(data['end_timestamp'], self.middle1)
        self.assertEqual(8 * 60 * 60, data['duration'])

    def test_within_range(self):
        with self._patch_get_stats(self.middle1, self.middle2):
            data = self._invoke_api()
        self._assert_times_match(data['start_timestamp'], self.middle1)
        self._assert_times_match(data['end_timestamp'], self.middle2)
        self.assertEqual(10 * 60 * 60, data['duration'])

    def test_within_range_zero_duration(self):
        with self._patch_get_stats(self.middle1, self.middle1):
            data = self._invoke_api()
        self._assert_times_match(data['start_timestamp'], self.middle1)
        self._assert_times_match(data['end_timestamp'], self.middle1)
        self.assertEqual(0, data['duration'])

    def test_overlap_range_end(self):
        with self._patch_get_stats(self.middle2, self.late1):
            data = self._invoke_api()
        self._assert_times_match(data['start_timestamp'], self.middle2)
        self._assert_times_match(data['end_timestamp'], self.end)
        self.assertEqual(((6 * 60) - 1) * 60, data['duration'])

    def test_after_range(self):
        with self._patch_get_stats(self.late1, self.late2):
            data = self._invoke_api()
        self.assertIsNone(data['start_timestamp'])
        self.assertIsNone(data['end_timestamp'])
        self.assertIsNone(data['duration'])

    def test_without_end_timestamp(self):
        with self._patch_get_stats(self.late1, self.late2):
            data = self.get(
                '/resources/resource-id/meters/instance:m1.tiny/duration',
                start_timestamp=self.late1.isoformat(),
                # this value doesn't matter, db call is mocked
                search_offset=10,
            )
        self._assert_times_match(data['start_timestamp'], self.late1)
        self._assert_times_match(data['end_timestamp'], self.late2)

    def test_without_start_timestamp(self):
        with self._patch_get_stats(self.early1, self.early2):
            data = self.get(
                '/resources/resource-id/meters/instance:m1.tiny/duration',
                end_timestamp=self.early2.isoformat(),
                # this value doesn't matter, db call is mocked
                search_offset=10,
            )
        self._assert_times_match(data['start_timestamp'], self.early1)
        self._assert_times_match(data['end_timestamp'], self.early2)
