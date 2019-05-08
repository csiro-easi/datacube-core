"""
S3IO Class

Low level byte read/writes to a single S3 object

Single-threaded. set new_session = False
Multi-threaded. set new_session = True

"""

import SharedArray as sa
import io
import os
import errno
import uuid
from itertools import repeat
from operator import mul
from os.path import expanduser
from pathlib import Path

import boto3
import boto3.session
from boto3.s3.transfer import TransferConfig
import botocore
import numpy as np
import sys
from pathos.multiprocessing import ProcessPool
from pathos.helpers import cpu_count
from six.moves import reduce, zip


# pylint: disable=too-many-locals, too-many-public-methods


class S3IO(object):
    """low level S3 byte IO interface.
    """

    # TODO: move boto3.session from Sig v2 to Sig v4 format and specify region,
    #       and store region of s3 bucket in postgres on ingest.
    #       this is confirmed to restores performance post boto3 > 1.4.3

    # enable_s3: True = reads/writes to s3
    # enable_s3: False = reads/writes to disk ***for testing only***
    def __init__(self, enable_s3=True, file_path=None, num_workers=cpu_count()):
        """Initialise the low level S3 byte IO interface.

        :param bool enable_s3: Flag to store objects in s3 or disk.
            True: store in S3
            False: store on disk (for testing purposes)
        :param str file_path: The root directory for the emulated s3 buckets when enable_se is set to False.
        :param int num_workers: The number of workers for parallel IO.
        """
        self.enable_s3 = enable_s3
        if file_path is None:
            self.file_path = expanduser("~") + "/S3IO/"
        else:
            self.file_path = file_path

        self.pool = ProcessPool(num_workers)

    def list_created_arrays(self):
        """List the created shared memory arrays.

          Arrays are prefixed by 'S3' or 'DCCORE'.

        :return: Returns the list of created arrays.
        """
        result = [f for f in os.listdir("/dev/shm") if f.startswith('S3') or f.startswith('DCCORE')]
        # TODO(csiro): Fix issue and remove pylint flag below
        # pylint: disable=superfluous-parens
        print(result)
        return result

    def delete_created_arrays(self):
        """Delete all created shared memory arrays.

          Arrays are prefixed by 'S3' or 'DCCORE'.
        """
        for a in self.list_created_arrays():
            sa.delete(a)

    def s3_resource(self, new_session=False):
        """Create a S3 resource.

        :param bool new_session: Flag to create a new session or reuse existing session.
            True: create new session
            False: reuse existing session
        :return: Returns a reference to the S3 resource.
        """
        if not self.enable_s3:
            return None
        config = botocore.config.Config(max_pool_connections=50)
        if new_session is True:
            s3 = boto3.session.Session().resource('s3', config=config)
        else:
            s3 = boto3.resource('s3', config=config)
        return s3

    def s3_bucket(self, s3_bucket, new_session=False):
        """get a reference to a S3 bucket.

        :param str s3_bucket: name of the s3 bucket.
        :param bool new_session: Flag to create a new session or reuse existing session.
            True: create new session
            False: reuse existing session
        :return: Returns a reference to the S3 bucket.
        """
        if not self.enable_s3:
            return None
        s3 = self.s3_resource(new_session)
        return s3.Bucket(s3_bucket)

    def s3_object(self, s3_bucket, s3_key, new_session=False):
        """get a reference to a S3 object.

        :param str s3_bucket: name of the s3 bucket.
        :param str s3_key: name of the s3 key.
        :param bool new_session: Flag to create a new session or reuse existing session.
            True: create new session
            False: reuse existing session
        :return: Returns a reference to the S3 object.
        """
        if not self.enable_s3:
            return None
        s3 = self.s3_resource(new_session)
        return s3.Bucket(s3_bucket).Object(s3_key)

    def list_buckets(self, new_session=False):
        """List S3 buckets.

        :param bool new_session: Flag to create a new session or reuse existing session.
            True: create new session
            False: reuse existing session
        :return: Returns list of Buckets
        """
        if self.enable_s3:
            try:
                s3 = self.s3_resource(new_session)
                return [b['Name'] for b in s3.meta.client.list_buckets()['Buckets']]
            except botocore.exceptions.ClientError as e:
                error_code = int(e.response['Error']['Code'])
                raise Exception("ClientError", error_code)
        else:
            directory = self.file_path
            return [f for f in os.listdir(directory) if os.path.isdir(os.path.join(directory, f))]

    def list_objects(self, s3_bucket, prefix='', max_keys=100, new_session=False):
        """List S3 objects.

        :param str s3_bucket: name of the s3 bucket.
        :param str prefix: prefix of buckets to list
        :param int max_keys: max keys to return
        :param bool new_session: Flag to create a new session or reuse existing session.
            True: create new session
            False: reuse existing session
        :return: Returns list of objects.
        """
        if self.enable_s3:
            try:
                s3 = self.s3_resource(new_session)
                objects = s3.meta.client.list_objects(Bucket=s3_bucket, Prefix=prefix, MaxKeys=max_keys)
                if 'Contents' not in objects:
                    return []
                return [o['Key'] for o in
                        s3.meta.client.list_objects(Bucket=s3_bucket, Prefix=prefix, MaxKeys=max_keys)['Contents']]
            except botocore.exceptions.ClientError as e:
                error_code = int(e.response['Error']['Code'])
                raise Exception("ClientError", error_code)
        else:
            directory = Path(self.file_path) / s3_bucket
            if directory.exists():
                if prefix != '':
                    prefix += '/'
                return [str(path.relative_to(directory))
                        for path in directory.glob('{}**/*'.format(prefix))
                        if path.is_file()]
            else:
                return []

    def delete_objects(self, s3_bucket, keys, new_session=False):
        """Delete S3 objects.

        :param str s3_bucket: name of the s3 bucket.
        :param int keys: list of s3 keys to delete
        :param bool new_session: Flag to create a new session or reuse existing session.
            True: create new session
            False: reuse existing session
        :return: Returns List of deleted objects.
        """
        if self.enable_s3:
            s3 = self.s3_resource(new_session)
            b = s3.Bucket(s3_bucket)
            key_list = dict(zip('Key', keys))
            key_list = [{'Key': v} for v in keys]
            response = b.delete_objects(Delete={'Objects': key_list})
            if 'ResponseMetadata' in response and 'HTTPStatusCode' in response['ResponseMetadata'] and \
                    response['ResponseMetadata']['HTTPStatusCode'] == 200 and 'Deleted' in response:
                return [d['Key'] for d in response['Deleted']]
        else:
            directory = Path(self.file_path) / s3_bucket
            response = []
            for k in keys:
                filepath = directory / k
                if filepath.exists() and filepath.is_file():
                    filepath.unlink()
                    response.append(k)
                    # Delete empty directories if any, mimicking S3 behaviour
                    parent = filepath.parent
                    while not list(parent.iterdir()):
                        parent.rmdir()
                        # Exit if we ever reach the root
                        if parent.parent == parent:
                            break
                        parent = parent.parent
            return response
        return []

    def bucket_exists(self, s3_bucket, new_session=False):
        """Check if bucket exists.

        :param str s3_bucket: name of the s3 bucket.
        :param bool new_session: Flag to create a new session or reuse existing session.
            True: create new session
            False: reuse existing session
        :return: Returns True if bucket exsits, otherwise False.
        """
        if self.enable_s3:
            try:
                s3 = self.s3_resource(new_session)
                s3.meta.client.head_bucket(Bucket=s3_bucket)
            except botocore.exceptions.ClientError as e:
                error_code = int(e.response['Error']['Code'])
                if error_code == 404:
                    return False
                raise Exception("ClientError", error_code)
            return True
        else:
            directory = self.file_path + "/" + str(s3_bucket)
            return os.path.exists(directory) and os.path.isdir(directory)

    def object_exists(self, s3_bucket, s3_key, new_session=False):
        """Check if object exists.

        :param str s3_bucket: name of the s3 bucket.
        :param str s3_key: name of the s3 key.
        :param bool new_session: Flag to create a new session or reuse existing session.
            True: create new session
            False: reuse existing session
        :return: Returns True if object exsits, otherwise False.
        """
        if self.enable_s3:
            try:
                s3 = self.s3_resource(new_session)
                s3.meta.client.head_object(Bucket=s3_bucket, Key=s3_key)
            except botocore.exceptions.ClientError as e:
                error_code = int(e.response['Error']['Code'])
                if error_code == 404:
                    return False
                raise Exception("ClientError", error_code)
            return True
        else:
            directory = self.file_path + "/" + str(s3_bucket) + "/" + str(s3_key)
            return os.path.exists(directory) and os.path.isfile(directory)

    def put_bytes(self, s3_bucket, s3_key, data, new_session=False):
        """Put bytes into a S3 object.

        :param str s3_bucket: name of the s3 bucket.
        :param str s3_key: name of the s3 key.
        :param bytes data: data to store in s3.
        :param bool new_session: Flag to create a new session or reuse existing session.
            True: create new session
            False: reuse existing session
        """
        # assert isinstance(data, memoryview), 'data must be a memoryview'

        # cctx = zstd.ZstdCompressor(level=9, write_content_size=True)
        # data = cctx.compress(data)

        if self.enable_s3:
            last_error = None
            for attempt in range(10):
                try:
                    s3 = self.s3_resource(new_session)
                    s3.meta.client.put_object(Bucket=s3_bucket, Key=s3_key, Body=io.BytesIO(data))
                    return
                except botocore.vendored.requests.packages.urllib3.exceptions.ReadTimeoutError as e:
                    last_error = str(e)
                    print("error - s3io.put_bytes()", str(type(e)), last_error)
                    continue
                except Exception as e:  # pylint: disable=broad-except
                    last_error = str(e)
                    print("error u - s3io.put_bytes()", str(type(e)), last_error)
                    continue
            # Exceeded max retries
            raise RuntimeError('s3io.put_bytes', 'exceeded max retries', last_error)
        else:
            filepath = Path(self.file_path) / s3_bucket / s3_key
            filepath.parent.mkdir(parents=True, exist_ok=True)
            with filepath.open('wb') as fh:
                fh.write(data)

    # # functionality for byte range put does not exist in S3 API
    # # need to do a get, change the bytes in the byte range and upload_part
    # # do later
    # def put_byte_range(self, s3_bucket, s3_key, data, s3_start, s3_end, new_session=False):
    #     if new_session is True:
    #         s3 = boto3.session.Session().resource('s3')
    #     else:
    #         s3 = boto3.resource('s3')
    #     s3.meta.client.put_object(Bucket=s3_bucket, Key=s3_key, Range='bytes='+str(s3_start)+'-'+str(s3_end-1),
    #                               Body=io.BytesIO(data))

    def put_bytes_mpu(self, s3_bucket, s3_key, data, block_size, new_session=False):
        """Put bytes into a S3 object using Multi-Part upload

        :param str s3_bucket: name of the s3 bucket.
        :param str s3_key: name of the s3 key.
        :param bytes data: data to store in s3.
        :param int block_size: block size for upload.
        :param bool new_session: Flag to create a new session or reuse existing session.
            True: create new session
            False: reuse existing session
        :return: Multi-part upload response
        """
        if not self.enable_s3:
            return self.put_bytes(s3_bucket, s3_key, data, new_session)

        if not isinstance(data, memoryview):
            data = memoryview(data)
        assert isinstance(data, memoryview), 'data must be a memoryview'
        s3 = self.s3_resource(new_session)
        mpu = s3.meta.client.create_multipart_upload(Bucket=s3_bucket, Key=s3_key)

        nbytes = reduce(mul, data.shape, 1) * data.itemsize
        num_blocks = int(np.ceil(nbytes / float(block_size)))
        parts_dict = dict(Parts=[])

        for block_number in range(num_blocks):
            part_number = block_number + 1
            start = block_number * block_size
            end = (block_number + 1) * block_size
            if end > nbytes:
                end = nbytes
            data_chunk = io.BytesIO(data[start:end])

            response = s3.meta.client.upload_part(Bucket=s3_bucket,
                                                  Key=s3_key,
                                                  UploadId=mpu['UploadId'],
                                                  PartNumber=part_number,
                                                  Body=data_chunk)

            parts_dict['Parts'].append(dict(PartNumber=part_number, ETag=response['ETag']))

        mpu_response = s3.meta.client.complete_multipart_upload(Bucket=s3_bucket,
                                                                Key=s3_key,
                                                                UploadId=mpu['UploadId'],
                                                                MultipartUpload=parts_dict)
        return mpu_response

    def put_bytes_mpu_mp(self, s3_bucket, s3_key, data, block_size, new_session=False):
        """Put bytes into a S3 object using Multi-Part upload in parallel

        :param str s3_bucket: name of the s3 bucket.
        :param str s3_key: name of the s3 key.
        :param bytes data: data to store in s3.
        :param int block_size: block size for upload.
        :param bool new_session: Flag to create a new session or reuse existing session.
            True: create new session
            False: reuse existing session
        :return: Multi-part upload response
        """

        def work_put(block_number, data, s3_bucket, s3_key, block_size, mpu):
            response = boto3.resource('s3').meta.client.upload_part(Bucket=s3_bucket,
                                                                    Key=s3_key,
                                                                    UploadId=mpu['UploadId'],
                                                                    PartNumber=block_number + 1,
                                                                    Body=data)

            return dict(PartNumber=block_number + 1, ETag=response['ETag'])

        if not self.enable_s3:
            return self.put_bytes(s3_bucket, s3_key, data, new_session)

        if not isinstance(data, memoryview):
            data = memoryview(data)
        s3 = self.s3_resource(new_session)

        mpu = s3.meta.client.create_multipart_upload(Bucket=s3_bucket, Key=s3_key)
        nbytes = reduce(mul, data.shape, 1) * data.itemsize
        num_blocks = int(np.ceil(nbytes / float(block_size)))
        data_chunks = []
        for block_number in range(num_blocks):
            start = block_number * block_size
            end = (block_number + 1) * block_size
            if end > nbytes:
                end = nbytes
            data_chunks.append(io.BytesIO(data[start:end]))

        parts_dict = dict(Parts=[])
        blocks = range(num_blocks)

        results = self.pool.map(work_put, blocks, data_chunks, repeat(s3_bucket), repeat(s3_key),
                                repeat(block_size), repeat(mpu))

        for result in results:
            parts_dict['Parts'].append(result)

        mpu_response = boto3.resource('s3').meta.client.complete_multipart_upload(Bucket=s3_bucket,
                                                                                  Key=s3_key,
                                                                                  UploadId=mpu['UploadId'],
                                                                                  MultipartUpload=parts_dict)

        return mpu_response

    def put_bytes_mpu_mp_shm(self, s3_bucket, s3_key, array_name, block_size, new_session=False):
        """Put bytes into a S3 object using Multi-Part upload in parallel with shared memory

        :param str s3_bucket: name of the s3 bucket.
        :param str s3_key: name of the s3 key.
        :param bytes data: data to store in s3.
        :param int block_size: block size for upload.
        :param bool new_session: Flag to create a new session or reuse existing session.
            True: create new session
            False: reuse existing session
        :return: Multi-part upload response
        """

        def work_put_shm(block_number, array_name, s3_bucket, s3_key, block_size, mpu):
            part_number = block_number + 1
            start = block_number * block_size
            end = (block_number + 1) * block_size
            shared_array = sa.attach(array_name)
            data_chunk = io.BytesIO(shared_array.data[start:end])

            s3 = boto3.session.Session().resource('s3')
            # s3 = boto3.resource('s3')
            response = s3.meta.client.upload_part(Bucket=s3_bucket,
                                                  Key=s3_key,
                                                  UploadId=mpu['UploadId'],
                                                  PartNumber=part_number,
                                                  Body=data_chunk)

            return dict(PartNumber=part_number, ETag=response['ETag'])

        if not self.enable_s3:
            data = sa.attach(array_name)
            return self.put_bytes(s3_bucket, s3_key, data, new_session)

        s3 = self.s3_resource(new_session)

        mpu = s3.meta.client.create_multipart_upload(Bucket=s3_bucket, Key=s3_key)

        shared_array = sa.attach(array_name)
        num_blocks = int(np.ceil(shared_array.nbytes / float(block_size)))
        parts_dict = dict(Parts=[])
        blocks = range(num_blocks)

        results = self.pool.map(work_put_shm, blocks, repeat(array_name), repeat(s3_bucket),
                                repeat(s3_key), repeat(block_size), repeat(mpu))

        for result in results:
            parts_dict['Parts'].append(result)

        mpu_response = s3.meta.client.complete_multipart_upload(Bucket=s3_bucket,
                                                                Key=s3_key,
                                                                UploadId=mpu['UploadId'],
                                                                MultipartUpload=parts_dict)
        return mpu_response

    def get_bytes(self, s3_bucket, s3_key, new_session=False, use_new=False):
        """Gets bytes from a S3 object

        :param str s3_bucket: name of the s3 bucket.
        :param str s3_key: name of the s3 key.
        :param bool new_session: Flag to create a new session or reuse existing session.
            True: create new session
            False: reuse existing session
        :return: Requested bytes
        """
        if self.enable_s3:
            # TODO: check and move to download_fileobj and upload_fileobj for transfers.
            #       similar performance as existing approach
            if use_new:
                s3 = boto3.client('s3')
                byte_buffer = io.BytesIO()
                # example config
                transfer_config = TransferConfig(multipart_chunksize=8*1024*1024, multipart_threshold=8*1024*1024,
                                                 max_concurrency=10)
                s3.download_fileobj(s3_bucket, s3_key, byte_buffer, Config=transfer_config)
                return byte_buffer.getvalue()
            else:
                last_error = None
                for attempt in range(10):
                    try:
                        s3 = self.s3_resource(new_session)
                        b = s3.Bucket(s3_bucket)
                        o = b.Object(s3_key)

                        #self.get_byte_range_mp(s3_bucket, s3_key, s3_start, s3_end, block_size, new_session)
                        #s3_end = o.get()['ContentLength']
                        #d = self.get_byte_range_mp(s3_bucket, s3_key, 0, s3_end, 10*1024*1024, new_session)
                        d = o.get()['Body'].read()
                        # d = np.frombuffer(d, dtype=np.uint8, count=-1, offset=0)
                        return d
                    except botocore.vendored.requests.packages.urllib3.exceptions.ReadTimeoutError as e:
                        last_error = str(e)
                        print("error - s3io.get_bytes()", str(type(e)), last_error)
                        continue
                    except Exception as e:  # pylint: disable=broad-except
                        last_error = str(e)
                        print("error u - s3io.get_bytes()", str(type(e)), last_error)
                        continue
                # Exceeded max retries
                raise RuntimeError('s3io.get_bytes', 'exceeded max retries', last_error)
        else:
            directory = self.file_path + "/" + str(s3_bucket)
            if not (os.path.exists(directory) and os.path.exists(directory + "/" + str(s3_key))):
                return None
            f = open(directory + "/" + str(s3_key), "rb")
            f.seek(0, 0)
            d = f.read()
            f.close()
            return d

        return None  # TODO: fix logic above, inserting this just to fix warnings

    def get_byte_range(self, s3_bucket, s3_key, s3_start, s3_end, new_session=False):
        """Gets bytes from a S3 object within a range.

        :param str s3_bucket: name of the s3 bucket.
        :param str s3_key: name of the s3 key.
        :param int s3_start: begin of range.
        :param int s3_end: begin of range.
        :param bool new_session: Flag to create a new session or reuse existing session.
            True: create new session
            False: reuse existing session
        :return: Requested bytes
        """
        if self.enable_s3:
            while True:
                s3 = self.s3_resource(new_session)
                b = s3.Bucket(s3_bucket)
                o = b.Object(s3_key)
                try:
                    d = o.get(Range='bytes=' + str(s3_start) + '-' + str(s3_end - 1))['Body'].read()
                    d = np.frombuffer(d, dtype=np.uint8, count=-1, offset=0)
                    return d
                except botocore.exceptions.ClientError as e:
                    break
                break
        else:
            directory = self.file_path + "/" + str(s3_bucket)
            if not (os.path.exists(directory) and os.path.exists(directory + "/" + str(s3_key))):
                return None
            f = open(directory + "/" + str(s3_key), "rb")
            f.seek(s3_start, 0)
            d = f.read(s3_end - s3_start)
            d = np.frombuffer(d, dtype=np.uint8, count=-1, offset=0)
            f.close()
            return d

        return None  # TODO: fix logic above, inserting this just to fix warnings

    def get_byte_range_mp(self, s3_bucket, s3_key, s3_start, s3_end, block_size, new_session=False):
        """Gets bytes from a S3 object within a range in parallel.

        :param str s3_bucket: name of the s3 bucket.
        :param str s3_key: name of the s3 key.
        :param int s3_start: begin of range.
        :param int s3_end: begin of range.
        :param int block_size: block size for download.
        :param bool new_session: Flag to create a new session or reuse existing session.
            True: create new session
            False: reuse existing session
        :return: Requested bytes
        """

        def work_get(block_number, array_name, s3_bucket, s3_key, s3_max_size, block_size):
            start = block_number * block_size
            end = (block_number + 1) * block_size
            if end > s3_max_size:
                end = s3_max_size
            d = self.get_byte_range(s3_bucket, s3_key, start, end, True)
            # d = np.frombuffer(d, dtype=np.uint8, count=-1, offset=0)
            shared_array = sa.attach(array_name)
            shared_array[start:end] = d

        if not self.enable_s3:
            return self.get_byte_range(s3_bucket, s3_key, s3_start, s3_end, new_session)

        s3 = self.s3_resource(new_session)

        s3o = s3.Bucket(s3_bucket).Object(s3_key).get()
        s3_max_size = s3o['ContentLength']
        s3_obj_size = s3_end - s3_start
        num_streams = int(np.ceil(s3_obj_size / block_size))
        blocks = range(num_streams)
        array_name = generate_array_name('S3IO' + '_' + s3_bucket + '_' + s3_key)
        sa.create(array_name, shape=s3_obj_size, dtype=np.uint8)
        shared_array = sa.attach(array_name)

        self.pool.map(work_get, blocks, repeat(array_name), repeat(s3_bucket), repeat(s3_key),
                      repeat(s3_max_size), repeat(block_size))

        sa.delete(array_name)
        return shared_array


def generate_array_name(basename):
    array_name = '_'.join([basename, str(uuid.uuid4()), str(os.getpid())])

    if sys.platform == 'darwin':
        return 'file://' + array_name
    else:
        return array_name
