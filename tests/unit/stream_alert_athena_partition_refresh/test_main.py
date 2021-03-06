"""
Copyright 2017-present, Airbnb Inc.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""
# pylint: disable=attribute-defined-outside-init,protected-access
# command: nosetests -v -s tests/unit/
# specific test: nosetests -v -s tests/unit/file.py:TestStreamPayload.test_name
from datetime import datetime
import json
import os

import boto3
from mock import call, patch
from moto import mock_sqs
from nose.tools import (
    assert_equal,
    assert_false,
    assert_is_instance,
    assert_is_none,
    assert_true,
    nottest,
    with_setup
)

import stream_alert.athena_partition_refresh as apr
from stream_alert.athena_partition_refresh.main import (
    handler,
    StreamAlertAthenaClient,
    StreamAlertSQSClient,
)
from tests.unit.helpers.aws_mocks import MockAthenaClient, MockSqsClient

TEST_REGION = 'us-east-2'

CONFIG_DATA = {
    'global': {
        'account': {
            'aws_account_id': '111111111111',
            'kms_key_alias': 'stream_alert_secrets',
            'prefix': 'unit-testing',
            'region': TEST_REGION
        },
        'terraform': {
            'tfstate_bucket': 'unit-testing.streamalert.terraform.state',
            'tfstate_s3_key': 'stream_alert_state/terraform.tfstate',
            'tfvars': 'terraform.tfvars'
        },
        'infrastructure': {
            'monitoring': {
                'create_sns_topic': True
            }
        }
    },
    'lambda': {
        'alert_processor_config': {
            'handler': 'stream_alert.alert_processor.main.handler',
            'source_bucket': 'unit-testing.streamalert.source',
            'source_current_hash': '<auto_generated>',
            'source_object_key': '<auto_generated>',
            'third_party_libraries': []
        },
        'rule_processor_config': {
            'handler': 'stream_alert.rule_processor.main.handler',
            'source_bucket': 'unit-testing.streamalert.source',
            'source_current_hash': '<auto_generated>',
            'source_object_key': '<auto_generated>',
            'third_party_libraries': [
                'jsonpath_rw',
                'netaddr'
            ]
        },
        'athena_partition_refresh_config': {
            'buckets': {
                'unit-testing.streamalerts': 'alerts',
                'unit-testing.streamalert.data': 'data'
            },
            'handler': 'main.handler',
            'timeout': '60',
            'memory': '128',
            'source_bucket': 'unit-testing.streamalert.source',
            'source_current_hash': '<auto_generated>',
            'source_object_key': '<auto_generated>',
            'third_party_libraries': []
        }
    }
}


class TestStreamAlertAthenaGlobals(object):
    """Test class for global functions in Athena Partition Refresh"""
    # pylint: disable=no-self-use
    @patch('stream_alert.athena_partition_refresh.main.LOGGER')
    @patch('stream_alert.athena_partition_refresh.main.load_config',
           return_value=CONFIG_DATA)
    @patch('stream_alert.athena_partition_refresh.main.StreamAlertSQSClient')
    @mock_sqs
    def test_handler_no_received_messages(
            self, mock_sqs_client, mock_config, mock_logging):
        """Athena - Handler - No Receieved Messages"""
        test_sqs_client = TestStreamAlertSQSClient()
        test_sqs_client.setup()
        mock_sqs_client.return_value.received_messages = []

        handler(None, None)

        mock_config.assert_called()
        assert_true(mock_logging.info.called)

    @patch('stream_alert.athena_partition_refresh.main.LOGGER')
    @patch('stream_alert.athena_partition_refresh.main.load_config',
           return_value=CONFIG_DATA)
    @patch('stream_alert.athena_partition_refresh.main.StreamAlertSQSClient')
    @mock_sqs
    def test_handler_no_unique_buckets(self, mock_sqs_client, mock_config, mock_logging):
        """Athena - Handler - No Unique Buckets"""
        test_sqs_client = TestStreamAlertSQSClient()
        test_sqs_client.setup()
        mock_sqs_client.return_value.unique_s3_buckets_and_keys = lambda: {}

        handler(None, None)

        mock_config.assert_called()
        assert_true(mock_logging.error.called)


class TestStreamAlertSQSClient(object):
    """Test class for StreamAlertSQSClient"""

    def setup(self):
        """Add a fake message to the queue."""
        self.mock_sqs = mock_sqs()
        self.mock_sqs.start()

        sqs = boto3.resource('sqs', region_name=TEST_REGION)

        prefix = CONFIG_DATA['global']['account']['prefix']
        name = StreamAlertSQSClient.DEFAULT_QUEUE_NAME.format(prefix)

        self.queue = sqs.create_queue(QueueName=name)
        self.client = StreamAlertSQSClient(CONFIG_DATA)

        # Create a fake s3 notification message to send
        bucket = 'unit-testing.streamalerts'
        test_s3_notification = {
            'Records': [
                {
                    'eventVersion': '2.0',
                    'eventSource': 'aws:s3',
                    'awsRegion': 'us-east-1',
                    'eventTime': '2017-08-07T18:26:30.956Z',
                    'eventName': 'S3:PutObject',
                    'userIdentity': {
                        'principalId': 'AWS:AAAAAAAAAAAAAAA'
                    },
                    'requestParameters': {
                        'sourceIPAddress': '127.0.0.1'
                    },
                    'responseElements': {
                        'x-amz-request-id': 'FOO',
                        'x-amz-id-2': 'BAR'
                    },
                    's3': {
                        's3SchemaVersion': '1.0',
                        'configurationId': 'queue',
                        'bucket': {
                            'name': bucket,
                            'ownerIdentity': {
                                'principalId': 'AAAAAAAAAAAAAAA'
                            },
                            'arn': 'arn:aws:s3:::{}'.format(bucket)
                        },
                        'object': {
                            'key': 'alerts/dt=2017-08-26-14-02/rule_name_alerts-1304134918401.json',
                            'size': 1494,
                            'eTag': '12214134141431431',
                            'versionId': 'asdfasdfasdf.dfadCJkj1',
                            'sequencer': '1212312321312321321'
                        }
                    }
                },
                {
                    'eventVersion': '2.0',
                    'eventSource': 'aws:s3',
                    'awsRegion': 'us-east-1',
                    'eventTime': '2017-08-07T18:26:30.956Z',
                    'eventName': 'S3:GetObject',
                    'userIdentity': {
                        'principalId': 'AWS:AAAAAAAAAAAAAAA'
                    },
                    'requestParameters': {
                        'sourceIPAddress': '127.0.0.1'
                    },
                    'responseElements': {
                        'x-amz-request-id': 'FOO',
                        'x-amz-id-2': 'BAR'
                    },
                    's3': {
                        's3SchemaVersion': '1.0',
                        'configurationId': 'queue',
                        'bucket': {
                            'name': bucket,
                            'ownerIdentity': {
                                'principalId': 'AAAAAAAAAAAAAAA'
                            },
                            'arn': 'arn:aws:s3:::{}'.format(bucket)
                        },
                        'object': {
                            # Different day than the above record
                            'key': 'alerts/dt=2017-08-27-14-02/rule_name_alerts-1304134918401.json',
                            'size': 1494,
                            'eTag': '12214134141431431',
                            'versionId': 'asdfasdfasdf.dfadCJkj1',
                            'sequencer': '1212312321312321321'
                        }
                    }
                }
            ]
        }
        self.queue.send_message(MessageBody=json.dumps(test_s3_notification),
                                QueueUrl=self.client.athena_sqs_url)

    def teardown(self):
        """Purge the Queue and reset the client between runs"""
        self.client.sqs_client.purge_queue(QueueUrl=self.client.athena_sqs_url)
        self.client = None

    @patch('stream_alert.athena_partition_refresh.main.LOGGER')
    def test_delete_messages_none_received(self, mock_logging):
        """Athena SQS - Delete Messages - No Receieved Messages"""
        self.client.delete_messages()

        assert_true(mock_logging.error.called)

    # The return value is not being mocked successfully
    @nottest
    @patch('stream_alert.athena_partition_refresh.main.StreamAlertSQSClient')
    @patch('stream_alert.athena_partition_refresh.main.LOGGER')
    def test_delete_messages_failure(self, mock_logging, mock_sqs_client):
        """Athena SQS - Delete Messages - Failure Response"""
        instance = mock_sqs_client.return_value
        instance.sqs_client.delete_message_batch.return_value = {'Failed': [{'Id': '1'}]}

        self.client.get_messages()
        self.client.unique_s3_buckets_and_keys()
        self.client.delete_messages()

        assert_true(mock_logging.error.called)

    @patch.object(StreamAlertSQSClient, 'SQS_BACKOFF_MAX_RETRIES', 1)
    @patch('stream_alert.athena_partition_refresh.main.LOGGER')
    @patch('boto3.client')
    def test_delete_messages_failure_retries(self, mock_sqs_client, mock_logging): #pylint: disable=no-self-use
        """Athena SQS - Delete Messages - Failure Response and push back messages to queue"""
        mock_sqs_client.return_value = MockSqsClient(failed=True)

        client = StreamAlertSQSClient(CONFIG_DATA)
        client.processed_messages = [{'MessageId': '1', 'ReceiptHandle': 'handle1'},
                                     {'MessageId': '2', 'ReceiptHandle': 'handle2'}]
        client.delete_messages()
        for message in client.processed_messages:
            assert_is_instance(message, dict)

        assert_true(mock_logging.error.called_with('Failed to delete the messages with following'))

    @patch('stream_alert.athena_partition_refresh.main.LOGGER')
    def test_delete_messages_none_processed(self, mock_logging):
        """Athena SQS - Delete Messages - No Processed Messages"""
        self.client.processed_messages = []
        result = self.client.delete_messages()

        assert_true(mock_logging.error.called)
        assert_false(result)

    @patch('stream_alert.athena_partition_refresh.main.LOGGER')
    def test_delete_messages(self, mock_logging):
        """Athena SQS - Delete Messages"""
        self.client.get_messages(max_tries=1)
        self.client.unique_s3_buckets_and_keys()
        self.client.delete_messages()

        assert_true(mock_logging.info.called)

    @patch('stream_alert.athena_partition_refresh.main.LOGGER')
    def test_get_messages_invalid_max_messages(self, mock_logging):
        """Athena SQS - Invalid Max Message Request"""
        resp = self.client.get_messages(max_messages=100)

        assert_true(mock_logging.error.called)
        assert_is_none(resp)

    @patch('stream_alert.athena_partition_refresh.main.LOGGER')
    def test_get_messages(self, mock_logging):
        """Athena SQS - Get Valid Messages"""
        self.client.get_messages(max_tries=1)

        assert_equal(len(self.client.received_messages), 1)
        assert_true(mock_logging.info.called)

    def test_unique_s3_buckets_and_keys(self):
        """Athena SQS - Get Unique Bucket Ids"""
        self.client.get_messages(max_tries=1)
        unique_buckets = self.client.unique_s3_buckets_and_keys()

        assert_equal(unique_buckets, {
            'unit-testing.streamalerts': set([
                'alerts/dt=2017-08-26-14-02/rule_name_alerts-1304134918401.json',
                'alerts/dt=2017-08-27-14-02/rule_name_alerts-1304134918401.json',
            ])
        })
        assert_equal(len(self.client.processed_messages), 2)

    @patch('stream_alert.athena_partition_refresh.main.LOGGER')
    def test_unique_s3_buckets_and_keys_invalid_sqs(self, mock_logging):
        """Athena SQS - Unique Buckets - Invalid SQS Message"""
        self.client.received_messages = ['wrong-format-test']
        unique_buckets = self.client.unique_s3_buckets_and_keys()

        assert_false(unique_buckets)
        assert_true(mock_logging.error.called)

    @patch('stream_alert.athena_partition_refresh.main.LOGGER')
    def test_unique_s3_buckets_and_keys_s3_test_event(self, mock_logging):
        """Athena SQS - Unique Buckets - S3 Test Event"""
        s3_test_event = {'Body': json.dumps({
            'HostId': '8cLeGAmw098X5cv4Zkwcmo8vvZa3eH3eKxsPzbB9wrR+YstdA6Knx4Ip8EXAMPLE',
            'Service': 'Amazon S3',
            'Bucket': 'bucketname',
            'RequestId': '5582815E1AEA5ADF',
            'Time': '2014-10-13T15:57:02.089Z',
            'Event': 's3:TestEvent'})}
        self.client.received_messages = [s3_test_event]
        unique_buckets = self.client.unique_s3_buckets_and_keys()

        assert_false(unique_buckets)
        assert_true(mock_logging.debug.called_with(
            'Skipping S3 bucket notification test event'))

    @patch('stream_alert.athena_partition_refresh.main.LOGGER')
    def test_unique_s3_buckets_and_keys_invalid_record(self, mock_logging):
        """Athena SQS - Unique Buckets - Missing Records Key in SQS Message"""
        self.client.received_messages = [{'Body': '{"missing-records-key": 1}'}]
        unique_buckets = self.client.unique_s3_buckets_and_keys()

        assert_false(unique_buckets)
        assert_true(mock_logging.error.called)

    @patch('stream_alert.athena_partition_refresh.main.LOGGER')
    def test_unique_s3_buckets_and_keys_non_s3_notification(self, mock_logging):
        """Athena SQS - Unique Buckets - Non S3 Notification"""
        self.client.received_messages = [{'Body': '{"Records": [{"kinesis": 1}]}'}]
        unique_buckets = self.client.unique_s3_buckets_and_keys()

        assert_false(unique_buckets)
        assert_true(mock_logging.info.called)
        assert_true(mock_logging.debug.called)

    @patch('stream_alert.athena_partition_refresh.main.LOGGER')
    def test_unique_s3_buckets_and_keys_no_mesages(self, mock_logging):
        """Athena SQS - Unique Buckets - No Receieved Messages"""
        self.client.received_messages = []
        unique_buckets = self.client.unique_s3_buckets_and_keys()

        assert_is_none(unique_buckets)
        assert_true(mock_logging.error.called)


class TestStreamAlertAthenaClient(object):
    """Test class for StreamAlertAthenaClient"""

    def setup(self):
        self.client = StreamAlertAthenaClient(CONFIG_DATA,
                                              results_key_prefix='unit-testing')

    @patch('stream_alert.athena_partition_refresh.main.LOGGER')
    def test_add_partition(self, mock_logging):
        """Athena - Add Hive Partition"""
        query_result = [
            {'Repair: added data to metastore:foobar'},
            {'Repair: added data to metastore:foobaz'}
        ]
        self.client.athena_client = MockAthenaClient(results=query_result)
        result = self.client.add_partition({
            'unit-testing.streamalerts': set([
                'alerts/dt=2017-08-26-14/rule_name_alerts-1304134918401.json',
                'alerts/dt=2017-08-27-14/rule_name_alerts-1304134918401.json'
            ]),
            'unit-testing.streamalert.data': set([
                'log_type_1/2017/08/26/14/test-data-11111-22222-33333.snappy',
                'log_type_2/2017/08/26/14/test-data-11111-22222-33333.snappy',
                'log_type_2/2017/08/26/15/test-data-11111-22222-33333.snappy',
                'log_type_2/2017/08/26/16/test-data-11111-22222-33333.snappy',
                'log_type_3/2017/08/26/14/test-data-11111-22222-33333.snappy',
                'log_type_1/2017/08/26/11/test-data-11111-22222-33333.snappy'
            ]),
            'test-bucket-with-data': set([
                '2017/08/26/14/rule_name_alerts-1304134918401.json',
                '2017/08/28/14/rule_name_alerts-1304134918401.json',
                '2017/07/30/14/rule_name_alerts-1304134918401.json'
            ])
        })

        assert_true(mock_logging.info.called)
        assert_true(result)

    @patch('stream_alert.athena_partition_refresh.main.LOGGER')
    def test_add_partition_unknown_bucket(self, mock_logging):
        """Athena - Add Hive Partition - Unknown Bucket"""
        self.client.athena_client = MockAthenaClient(results=[])
        result = self.client.add_partition({
            'bucket-not-in-config.streamalerts': set([
                'alerts/dt=2017-08-26-14/rule_name_alerts-1304134918401.json',
                'alerts/dt=2017-08-27-14/rule_name_alerts-1304134918401.json',
            ])
        })

        assert_true(mock_logging.error.called)
        assert_false(result)

    @patch('stream_alert.athena_partition_refresh.main.LOGGER')
    def test_add_partition_unexpected_s3_key(self, mock_logging):
        """Athena - Add Hive Partition - Unexpected S3 Key"""
        self.client.athena_client = MockAthenaClient(results=[])
        result = self.client.add_partition({
            'unit-testing.streamalerts': set([
                'a/pattern/that/does/not-match'
            ]),
            'test-bucket-with-data': set([
                'another/pattern/that/does/not-match'
            ])
        })

        assert_true(mock_logging.error.called)
        assert_false(result)

    def test_check_table_exists(self):
        """Athena - Check Table Exists"""
        query_result = [{'alerts': True}]
        self.client.athena_client = MockAthenaClient(results=query_result)

        result = self.client.check_table_exists('unit-test')
        assert_true(result)

        generated_results_key = 'unit-testing/{}'.format(
            datetime.now().strftime('%Y/%m/%d'))
        assert_equal(self.client.athena_results_key, generated_results_key)

    @patch('stream_alert.athena_partition_refresh.main.LOGGER')
    def test_check_table_exists_invalid(self, mock_logging):
        """Athena - Check Table Exists - Does Not Exist"""
        query_result = None
        self.client.athena_client = MockAthenaClient(results=query_result)

        result = self.client.check_table_exists('unit-test')
        assert_false(result)
        assert_true(mock_logging.info.called)

    def test_check_database_exists_invalid(self):
        """Athena - Check Database Exists - Does Not Exist"""
        query_result = None
        self.client.athena_client = MockAthenaClient(results=query_result)

        assert_false(self.client.check_database_exists())

    def test_check_database_exists(self):
        """Athena - Check Database Exists"""
        query_result = [{'streamalert': True}]
        self.client.athena_client = MockAthenaClient(results=query_result)

        assert_true(self.client.check_database_exists())

    @patch('stream_alert.athena_partition_refresh.main.LOGGER')
    def test_run_athena_query_empty(self, mock_logging):
        """Athena - Run Athena Query - Empty Result"""
        query_result = None
        self.client.athena_client = MockAthenaClient(results=query_result)

        query_success, query_results = self.client.run_athena_query(
            query='SHOW DATABASES;'
        )

        assert_true(query_success)
        assert_equal(query_results['ResultSet']['Rows'], [])
        assert_true(mock_logging.debug.called)

    def test_run_athena_query_async(self):
        """Athena - Run Athena Query - Async Call"""
        query_result = []
        self.client.athena_client = MockAthenaClient(results=query_result)

        query_success, _ = self.client.run_athena_query(
            query='SHOW DATABASES;',
            async=True
        )

        assert_true(query_success)

    @patch('stream_alert.athena_partition_refresh.main.LOGGER')
    def test_run_athena_query_error(self, mock_logging):
        """Athena - Run Athena Query - Error Result"""
        self.client.athena_client = MockAthenaClient(results=None, result_state='FAILED')

        query_success, query_results = self.client.run_athena_query(
            query='SHOW DATABASES;'
        )

        assert_true(mock_logging.error.called)
        assert_false(query_success)
        assert_equal(query_results, {})

    def test_run_athena_query(self):
        """Athena - Run Athena Query - Normal Result"""
        self.client.athena_client = MockAthenaClient()

        query_success, query_results = self.client.run_athena_query(
            query='SHOW DATABASES;'
        )

        assert_true(query_success)
        assert_equal(query_results['ResultSet']['Rows'], [{'Data': [{'test': 'test'}]}])


def _teardown_env():
    """Helper method to reset environment variables"""
    if 'LOGGER_LEVEL' in os.environ:
        del os.environ['LOGGER_LEVEL']


@with_setup(setup=None, teardown=_teardown_env)
@patch('stream_alert.athena_partition_refresh.LOGGER.error')
def test_init_logging_bad(log_mock):
    """Athena Parition Refresh Init - Logging, Bad Level"""
    level = 'IFNO'

    os.environ['LOGGER_LEVEL'] = level

    # Force reload the athena_partition_refresh package to trigger the init
    reload(apr)

    message = str(call('Defaulting to INFO logging: %s',
                       ValueError('Unknown level: \'IFNO\'',)))

    assert_equal(str(log_mock.call_args_list[0]), message)


@with_setup(setup=None, teardown=_teardown_env)
@patch('stream_alert.athena_partition_refresh.LOGGER.setLevel')
def test_init_logging_int_level(log_mock):
    """Athena Parition Refresh Init - Logging, Integer Level"""
    level = '10'

    os.environ['LOGGER_LEVEL'] = level

    # Force reload the athena_partition_refresh package to trigger the init
    reload(apr)

    log_mock.assert_called_with(10)
