# Copyright 2015 IBM All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import json as json_import
import os
import requests
try:
    from http.cookiejar import CookieJar  # Python 3
except ImportError:
    from cookielib import CookieJar  # Python 2


def load_from_vcap_services(service_name):
    vcap_services = os.getenv("VCAP_SERVICES")
    if vcap_services is not None:
        services = json_import.loads(vcap_services)
        if service_name in services:
            return services[service_name][0]["credentials"]
    else:
        return None


class WatsonException(Exception):
    """Generic exception class."""
    pass


class WatsonInvalidArgument(Exception):
    """A parameter to a function or methods was invalid"""
    pass


def _remove_null_values(dictionary):
    if isinstance(dictionary, dict):
        return {k: v for k, v in dictionary.items() if v is not None}
    return dictionary


def _convert_boolean_value(value):
    if isinstance(value, bool):
        return 1 if value else 0
    return value


def _convert_boolean_values(dictionary):
    if isinstance(dictionary, dict):
        return {k: _convert_boolean_value(v) for k, v in dictionary.items()}
    return dictionary


class WatsonDeveloperCloudService(object):
    def __init__(self, vcap_services_name, url, username=None, password=None, use_vcap_services=True, api_key=None):
        """
        Loads credentials from the VCAP_SERVICES environment variable if available, preferring credentials explicitly
        set in the request.
        If VCAP_SERVICES is not found (or use_vcap_services is set to False), username and password credentials must
        be specified.
        """

        self.url = url
        self.jar = None
        self.api_key = None
        self.username = None
        self.password = None

        if api_key is not None:
            if username is not None or password is not None:
                raise WatsonInvalidArgument('Cannot set api_key and username and password together')
            self.set_api_key(api_key)
        else:
            self.set_username_and_password(username, password)

        if use_vcap_services and not self.username and not self.api_key:
            self.vcap_service_credentials = load_from_vcap_services(vcap_services_name)
            if self.vcap_service_credentials is not None and isinstance(self.vcap_service_credentials, dict):
                self.url = self.vcap_service_credentials['url']
                if 'username' in self.vcap_service_credentials:
                    self.username = self.vcap_service_credentials['username']
                if 'password' in self.vcap_service_credentials:
                    self.password = self.vcap_service_credentials['password']
                if 'apikey' in self.vcap_service_credentials:
                    self.api_key = self.vcap_service_credentials['apikey']

        if (self.username is None or self.password is None) and self.api_key is None:
            raise WatsonException('You must specific your username and password service credentials ' +
                                  '(Note: these are different from your Bluemix id)')

    def set_username_and_password(self, username=None, password=None):
        if username == 'YOUR SERVICE USERNAME':
            username = None
        if password == 'YOUR SERVICE PASSWORD':
            password = None

        self.username = username
        self.password = password
        self.jar = CookieJar()

    def set_api_key(self, api_key):
        if api_key == 'YOUR API KEY':
            api_key = None

        self.api_key = api_key
        self.jar = CookieJar()

    def set_url(self, url):
        self.url = url

    # Could make this compute the label_id based on the variable name of the dictionary passed in (using **kwargs), but
    # this might be confusing to understand.
    @staticmethod
    def unpack_id(dictionary, label_id):
        if isinstance(dictionary, dict) and label_id in dictionary:
            return dictionary[label_id]
        return dictionary

    def _get_error_message(self, response):
        '''
        Gets the error message from a JSON response.
        {
            code: 400
            error: 'Bad request'
        }
        '''
        error_message = 'Unknown error'
        try:
            error_json = response.json()
            if 'error' in error_json:
                error_message = error_json['error']
            if 'error_message' in error_json:
                error_message = error_json['error_message']
        except:
            pass
        return error_message

    def _alchemy_html_request(self, method_name=None, url=None, html=None, text=None, params=None, method='POST',
                              method_url=None):
        if params is None:
            params = {}
        params['outputMode'] = 'json'
        headers = {'content-type': 'application/x-www-form-urlencoded'}
        url_encoded_params = {'html': html, 'text': text}
        params = _convert_boolean_values(params)

        if method_url is None:
            if url:
                params['url'] = url
                method_url = '/url/URL' + method_name
            elif html:
                method_url = '/html/HTML' + method_name
            elif text:
                method_url = '/text/Text' + method_name
            else:
                raise WatsonInvalidArgument('url, html or text must be specified')

        return self.request(method=method, url=method_url, params=params, data=url_encoded_params, headers=headers,
                            accept_json=True)

    def _alchemy_image_request(self, method_name, image_file=None, image_url=None, params=None):
        if params is None:
            params = {}
        params['outputMode'] = 'json'
        params = _convert_boolean_values(params)
        headers = {}
        image_contents = None

        if image_file:
            params['imagePostMode'] = 'raw'
            image_contents = image_file.read()
            # headers['content-length'] = sys.getsizeof(image_contents)
            url = '/image/Image' + method_name
        elif image_url:
            params['imagePostMode'] = 'not-raw'
            params['url'] = image_url
            url = '/url/URL' + method_name
        else:
            raise WatsonInvalidArgument('image_file or image_url must be specified')

        return self.request(method='POST', url=url, params=params, data=image_contents, headers=headers,
                            accept_json=True)

    def request(self, method, url, accept_json=False, headers=None, params=None, json=None, data=None, **kwargs):
        full_url = self.url + url

        if accept_json:
            json_headers = {'accept': 'application/json'}
            if headers:
                json_headers.update(headers)
            headers = json_headers

        # Remove keys with None values
        headers = _remove_null_values(headers)
        params = _remove_null_values(params)
        json = _remove_null_values(json)
        data = _remove_null_values(data)

        auth = None
        if self.username and self.password:
            auth = (self.username, self.password)
        if self.api_key is not None:
            if params is None:
                params = {}
            params['apikey'] = self.api_key

        response = requests.request(method=method, url=full_url, cookies=self.jar, auth=auth, headers=headers,
                                    params=params, json=json, data=data, **kwargs)

        if 200 <= response.status_code <= 299:
            if accept_json:
                response_json = response.json()
                if 'status' in response_json and response_json['status'] == 'ERROR':
                    response.status_code = 400
                    error_message = 'Unknown error'
                    if 'statusInfo' in response_json:
                        error_message = response_json['statusInfo']
                    if error_message == 'invalid-api-key':
                        response.status_code = 401
                    raise WatsonException('Error: ' + error_message)
                return response_json
            return response
        else:
            if response.status_code == 401:
                error_message = 'Unauthorized: Access is denied due to invalid credentials'
            else:
                error_message = self._get_error_message(response)

            raise WatsonException('Error: ' + error_message + ', Code: ' + str(response.status_code))
