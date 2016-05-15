
import re
import os
import shutil

# XML
from xml.etree import ElementTree

# YAML
import yaml

# Dateutil
import pytz
import dateutil.parser
import datetime

# SHA1-HMAC
import sha
import hmac
import base64
import hashlib

# WebApp
from flask import Flask
from flask import jsonify
from flask import request
from flask import Response

# Include
import exception
import util

app = Flask(__name__)
app.debug = True


class RequestType():
    VirtualHost = 1
    Path = 2


class StorageSettings():
    settings = None

    @classmethod
    def load(cls, filepath):
        """Load Settings yaml."""
        with open(filepath, 'r') as f:
            cls.settings = yaml.load(f)
            f.close()

    @classmethod
    def has_bucket(cls, bucket_name):
        """Get bucket exists."""
        return bucket_name in cls.settings['buckets']

    @classmethod
    def get_credential(cls, bucket_name, access_key_id):
        """Get specified credential."""
        credentials = filter(
            lambda x: x['access_key_id'] == access_key_id,
            cls.settings['buckets'][bucket_name]['credentials']
        )
        if len(credentials) == 1:
            return credentials[0]
        else:
            return None

    @classmethod
    def get_secret_access_key(cls, bucket_name, access_key_id):
        """Get Secret Access Key from settings."""
        credential = cls.get_credential(bucket_name, access_key_id)
        if credential:
            return credential['secret_access_key']
        else:
            return None

    @classmethod
    def permission_check(cls, bucket_name, access_key_id, key):
        """Permission Check."""
        credential = cls.get_credential(bucket_name, access_key_id)
        if not credential['permission'][key]:
            raise exception.AccessDenied()


@app.errorhandler(exception.AppException)
def handle_invalid_usage(error):
    """Output Error."""
    response = jsonify(status_code=error.status_code, message=error.message)
    response.status_code = error.status_code
    return response


def get_request_access_key_id():
    """Get Access Key ID from request header."""
    auth_string = request.headers.get('Authorization').split(' ')[1]
    return auth_string.split(':')[0]


def get_request_information(path_string):
    """Analyze Request."""
    # Remove URL Query
    if path_string.count('?') > 0:
        path_string = path_string.split('?', 1)[0]
    # Virtual Host Type
    bucket_name = re.match(
        '(.*).{0}'.format(StorageSettings.settings['app']['virtual_host']),
        request.headers.get('Host'))
    if bucket_name:
        bucket_name = bucket_name.group(1)
        remote_path = path_string
        return bucket_name, remote_path, RequestType.VirtualHost
    # Path Type
    if path_string.count('/') == 0:
        bucket_name = path_string
        remote_path = ''
    else:
        splited_path_string = path_string.split('/', 1)
        bucket_name = splited_path_string[0]
        remote_path = splited_path_string[1]
    return bucket_name, remote_path, RequestType.Path


def validation_request_header(keys):
    """Check requirement key exsists."""
    for key in keys:
        if key not in request.headers:
            raise exception.InvalidArgument()


def validation_request_authorization():
    """Check Authorization Header."""
    auth_string = request.headers.get('Authorization').split(' ')
    if len(auth_string) != 2:
        raise exception.InvalidArgument()
    if auth_string[0] != 'AWS':
        raise exception.InvalidArgument()
    if auth_string[1].count(':') != 1:
        raise exception.InvalidArgument()


def validation_date():
    """Requested date check."""
    try:
        date = dateutil.parser.parse(request.headers.get('Date'))
    except exception.TypeError:
        raise exception.InvalidArgument()
    tz_tokyo = pytz.timezone('Asia/Tokyo')
    diff = datetime.datetime.now(tz_tokyo) - date
    if diff > datetime.timedelta(minutes=3):
        raise exception.InvalidArgument()


def validation_filesize(size):
    """validate uploaded data length."""
    if len(request.data) != int(size):
        raise exception.InvalidArgument()


def authorization_request(bucket_name, access_key_id, raw_string):
    """Authorization."""
    if not StorageSettings.has_bucket(bucket_name):
        print('Err: NoSuchBucket')
        raise exception.NoSuchBucket()
    # Check: Access Key ID
    secret_access_key = StorageSettings.get_secret_access_key(
        bucket_name, access_key_id)
    if secret_access_key is None:
        print('Err: InvalidAccessKeyId')
        raise exception.InvalidAccessKeyId()
    # Generate Token
    hashed = hmac.new(secret_access_key, raw_string, hashlib.sha1).digest()
    calc_token = 'AWS {0}:{1}'.format(
        access_key_id, base64.encodestring(hashed).rstrip()
    )
    if calc_token != request.headers.get('Authorization'):
        print('Err: SignatureDoesNotMatch')
        raise exception.SignatureDoesNotMatch()


def convert_local_path(bucket_name, remote_path):
    """Generate local filepath."""
    return os.path.abspath(
        os.path.join(
            StorageSettings.settings['buckets'][bucket_name]['root_path'],
            remote_path
        )
    )


def detect_x_amz():
    """Detect X-AMZ Header and return string for authorization."""
    ret = ''
    for key in sorted(
            filter(
                lambda x: x[0].startswith('X-Amz-'), request.headers.items()
            )
    ):
        k = key[0].lower()
        v = request.headers.get(key[0])
        ret += '{}:{}\n'.format(k, v)
    return ret


@app.route("/", methods=['HEAD'])
def head_root():
    """Check Bucket Accessing Permission."""
    # Process Header
    validation_request_header(['Host', 'Date', 'Authorization'])
    validation_request_authorization()
    validation_date()
    bucket_name, remote_path, request_type = get_request_information('')
    access_key_id = get_request_access_key_id()
    print('bucket_name:[{}]'.format(bucket_name))
    print('remote_path:[{}]'.format(remote_path))
    print('request_type:[{}]'.format(request_type))
    if request_type == RequestType.VirtualHost:
        authorization_request(
            bucket_name,
            access_key_id,
            'HEAD\n\n\n{0}\n/{1}/'.format(
                request.headers.get('Date'),
                bucket_name
            )
        )
        return ('', 200)
    raise exception.NotImplemented()


@app.route("/<path:path_string>", methods=['HEAD'])
def head_object(path_string):
    """Check Object Accessing Permission."""
    validation_request_header(['Host', 'Date', 'Authorization'])
    validation_request_authorization()
    validation_date()
    bucket_name, remote_path, request_type = get_request_information(
        path_string
    )
    access_key_id = get_request_access_key_id()
    print('bucket_name:[{}]'.format(bucket_name))
    print('remote_path:[{}]'.format(remote_path))
    print('request_type:[{}]'.format(request_type))
    print('path_string:[{}]'.format(path_string))
    authorization_request(
        bucket_name,
        access_key_id,
        'HEAD\n\n\n{0}\n/{1}/{2}'.format(
            request.headers.get('Date'),
            bucket_name,
            remote_path
        )
    )
    # Exists Check
    local_path = convert_local_path(bucket_name, remote_path)
    if not os.path.exists(local_path):
        return ('', 404)
    return ('', 200)


def listing_object(bucket_name):
    """List objects and common prefix."""
    # Get Query Parameter
    delimiter_string = request.args.get('delimiter', '')
    marker_string = request.args.get('marker', '')
    max_keys_string = request.args.get('max-keys', '1000')
    prefix_string = request.args.get('prefix', '')
    print('delimiter:[{}]'.format(delimiter_string))
    print('marker:[{}]'.format(marker_string))
    print('max-keys:[{}]'.format(max_keys_string))
    print('prefix:[{}]'.format(prefix_string))
    # Detect Bucket objects
    objects = list()
    common_prefixs = list()
    bucket_root = convert_local_path(bucket_name, '')
    prefix_root = convert_local_path(bucket_name, prefix_string)
    if delimiter_string == '':
        for root, dirs, files in os.walk(prefix_root):
            for file in files:
                abspath = os.path.abspath(os.path.join(root, file))
                relpath = abspath[len('{}/'.format(bucket_root)):]
                objects.append(relpath)
    elif delimiter_string == '/':
        for object_on_prefix in os.listdir(prefix_root):
            abspath = os.path.join(prefix_root, object_on_prefix)
            relpath = abspath[len('{}/'.format(bucket_root)):]
            if os.path.isdir(abspath):
                common_prefixs.append('{}/'.format(relpath))
            else:
                objects.append(relpath)
    else:
        raise exception.NotImplemented()
    # Generate XML (Header part)
    top = ElementTree.Element(
        'ListBucketResult',
        {'xmlns': 'http://s3.amazonaws.com/doc/2006-03-01/'})
    ElementTree.SubElement(top, 'Name').text = bucket_name
    ElementTree.SubElement(top, 'Prefix').text = prefix_string
    ElementTree.SubElement(top, 'Delimiter').text = delimiter_string
    # ElementTree.SubElement(top, 'Marker')
    # ElementTree.SubElement(top, 'NextMarker')
    ElementTree.SubElement(top, 'KeyCount').text = str(len(objects))
    ElementTree.SubElement(top, 'MaxKeys').text = max_keys_string
    ElementTree.SubElement(top, 'IsTruncated').text = 'false'
    # Generate XML (Objects part)
    for object in objects:
        origin_object = object
        object = convert_local_path(bucket_name, object)
        with open(object, 'rb') as f:
                checksum = hashlib.md5(f.read()).hexdigest()
        # Get Parameters of file
        last_modified = datetime.datetime.fromtimestamp(
            os.stat(object).st_mtime
        ).isoformat()
        etag = '&quot;{}&quot;'.format(checksum)
        size = '{}'.format(os.path.getsize(object))
        contents = ElementTree.SubElement(top, 'Contents')
        ElementTree.SubElement(contents, 'Key').text = '{}'.format(
            origin_object
        )
        ElementTree.SubElement(contents, 'LastModified').text = last_modified
        ElementTree.SubElement(contents, 'ETag').text = etag
        ElementTree.SubElement(contents, 'Size').text = size
        ElementTree.SubElement(contents, 'StorageClass').text = 'Standard'
        # owner = ElementTree.SubElement(contents, 'Owner')
        # ElementTree.SubElement(owner, 'ID').text = '0001'
        # ElementTree.SubElement(owner, 'DisplayName').text = 'DefaultUser'
    # CommonPrefix
    cp = ElementTree.SubElement(top, 'CommonPrefixes')
    for common_prefix in common_prefixs:
        ElementTree.SubElement(cp, 'Prefix').text = common_prefix
    # Response
    xml_data = util.xml_prettify(top)
    return Response(xml_data, mimetype='application/xml')


def return_object(local_path, content_type='application/octet-stream'):
    """Return Object Data."""
    if not os.path.exists(local_path):
        raise exception.NoSuchKey()
    if not os.path.isfile(local_path):
        raise exception.InvalidArgument()
    data = ''
    with open(local_path, 'rb') as f:
        data = f.read()
        f.close()
    return Response(response=data, content_type=content_type)


@app.route("/", methods=['GET'])
def get_root():
    """Listing Object ."""
    # Process Header
    validation_request_header(['Host', 'Date', 'Authorization'])
    validation_request_authorization()
    validation_date()

    bucket_name, remote_path, request_type = get_request_information('')
    access_key_id = get_request_access_key_id()

    print('bucket_name:[{}]'.format(bucket_name))
    print('remote_path:[{}]'.format(remote_path))
    print('request_type:[{}]'.format(request_type))

    if request_type != RequestType.VirtualHost:
        raise exception.NotImplemented()

    authorization_request(
        bucket_name,
        access_key_id,
        'GET\n\n\n{}\n{}/{}/'.format(
            request.headers.get('Date'),
            detect_x_amz(),
            bucket_name
        )
    )
    StorageSettings.permission_check(bucket_name, access_key_id, 'list')
    return listing_object(bucket_name)


@app.route("/<path:path_string>", methods=['GET'])
def get_object(path_string):
    """Download Object ."""
    validation_request_header(['Host', 'Date', 'Authorization'])
    validation_request_authorization()
    validation_date()
    bucket_name, remote_path, request_type = get_request_information(
        path_string
    )
    access_key_id = get_request_access_key_id()
    print('bucket_name:[{}]'.format(bucket_name))
    print('remote_path:[{}]'.format(remote_path))
    print('request_type:[{}]'.format(request_type))
    print('path_string:[{}]'.format(path_string))
    authorization_request(
        bucket_name,
        access_key_id,
        'GET\n\n\n{}\n{}/{}/{}'.format(
            request.headers.get('Date'),
            detect_x_amz(),
            bucket_name,
            remote_path,
        )
    )
    if remote_path == '':
        StorageSettings.permission_check(bucket_name, access_key_id, 'list')
        return listing_object(bucket_name)
    else:
        local_path = convert_local_path(bucket_name, remote_path)
        print('local_path:[{}]'.format(local_path))
        StorageSettings.permission_check(bucket_name, access_key_id, 'download')
        return return_object(local_path)


def fileupload(bucket_name, remote_path):
    """Process Uploaded file."""
    local_path = convert_local_path(bucket_name, remote_path)
    dir_path = os.path.dirname(local_path)
    # Create Directories
    try:
        os.makedirs(dir_path)
    except OSError:
        pass
    # Write posted data to file
    with open(local_path, 'wb') as f:
        f.write(request.data)
        f.close()
    # Check MD5
    with open(local_path, 'rb') as f:
        checksum = hashlib.md5(f.read()).hexdigest()
    # Response
    headers = {
        'ETag': '"{}"'.format(checksum)
    }
    return Response('OK', headers=headers)


def createdirectory(bucket_name, remote_path):
    """Process creating directory request."""
    local_path = convert_local_path(bucket_name, remote_path)
    try:
        os.makedirs(local_path)
    except OSError:
        pass
    return Response('OK')


@app.route("/<path:path_string>", methods=['PUT'])
def put_object(path_string):
    """Create Object."""
    validation_request_header(
        ['Host', 'Date', 'Content-Length', 'Content-Type', 'Authorization']
    )
    validation_request_authorization()
    validation_date()
    validation_filesize(request.headers.get('Content-Length'))

    bucket_name, remote_path, request_type = get_request_information(
        path_string
    )
    access_key_id = get_request_access_key_id()

    print('bucket_name:[{}]'.format(bucket_name))
    print('remote_path:[{}]'.format(remote_path))
    print('request_type:[{}]'.format(request_type))
    print('path_string:[{}]'.format(path_string))

    authorization_request(
        bucket_name,
        access_key_id,
        'PUT\n{}\n{}\n{}\n{}/{}/{}'.format(
            request.headers.get('Content-Md5', ''),
            request.headers.get('Content-Type', ''),
            request.headers.get('Date'),
            detect_x_amz(),
            bucket_name,
            remote_path
        )
    )

    if remote_path[-1] == '/':
        StorageSettings.permission_check(bucket_name, access_key_id, 'mkdir')
        return createdirectory(bucket_name, remote_path)
    else:
        StorageSettings.permission_check(bucket_name, access_key_id, 'upload')
        return fileupload(bucket_name, remote_path)


@app.route("/<path:path_string>", methods=['DELETE'])
def delete_object(path_string):
    """Deleting Object."""
    validation_request_header(['Host', 'Date', 'Authorization'])
    validation_request_authorization()
    validation_date()
    bucket_name, remote_path, request_type = get_request_information(
        path_string
    )
    access_key_id = get_request_access_key_id()
    authorization_request(
        bucket_name,
        access_key_id,
        'DELETE\n\n\n{0}\n/{1}/{2}'.format(
            request.headers.get('Date'),
            bucket_name,
            remote_path
        )
    )
    StorageSettings.permission_check(bucket_name, access_key_id, 'delete')
    print('*Deleting...{}'.format(remote_path))
    local_path = convert_local_path(bucket_name, remote_path)
    if not os.path.exists(local_path):
        raise exception.NoSuchKey()
    if remote_path[-1] == '/':
        shutil.rmtree(local_path)
    else:
        os.remove(local_path)
    return ('', 204)

StorageSettings.load('settings.yaml')

if __name__ == "__main__":
    print('[Settings]')
    print(StorageSettings.settings)
    app.run(
        host=StorageSettings.settings['app']['host'],
        port=StorageSettings.settings['app']['port']
    )
