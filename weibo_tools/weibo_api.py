#!/usr/bin/env python
# -*- coding: utf-8 -*-
try:
    import ujson as json
except ImportError,e:
    import json

import time
import urllib
import socket
import re
import logging
import httplib
import random
import urlparse
import gzip
from cStringIO import StringIO
API_RemoteIP=None
InterfaceIP=None

token_error=set((21314,21315,21316,21317,21319,21327))
def UseRandomLocalAddress():
    global InterfaceIP
    names,aliases,ips = socket.gethostbyname_ex(socket.gethostname())
    print ips
    to_use_ip=set()
    for ip in ips :
        if not re.match('^(192.)|(10.)|(127.)',ip):
            to_use_ip.add(ip)
            print 'use ip:',ip
    InterfaceIP=list(to_use_ip)

class APIError(StandardError):
    '''
    raise APIError if got failed json message.
    '''
    def __init__(self, error_code, error, request):
        self.error_code = error_code
        self.error = error
        self.request = request
        StandardError.__init__(self, error)
    def isOauthFail(self):
        return self.error in token_error
    def __str__(self):
        return 'APIError: %s: %s, request: %s' % (self.error_code, self.error, self.request)

def _encode_params(**kw):
    '''
    Encode parameters.
    '''
    args = []
    for k, v in kw.iteritems():
        qv = v.encode('utf-8') if isinstance(v, unicode) else str(v)
        args.append('%s=%s' % (k, urllib.quote(qv)))
    return '&'.join(args)

def _encode_multipart(**kw):
    '''
    Build a multipart/form-data body with generated random boundary.
    '''
    boundary = '----------%s' % hex(int(time.time() * 1000))
    data = []
    for k, v in kw.iteritems():
        data.append('--%s' % boundary)
        if hasattr(v, 'read'):
            # file-like object:
            ext = ''
            filename = getattr(v, 'name', '')
            n = filename.rfind('.')
            if n != (-1):
                ext = filename[n:].lower()
            content = v.read()
            data.append('Content-Disposition: form-data; name="%s"; filename="hidden"' % k)
            data.append('Content-Length: %d' % len(content))
            data.append('Content-Type: %s\r\n' % _guess_content_type(ext))
            data.append(content)
        else:
            data.append('Content-Disposition: form-data; name="%s"\r\n' % k)
            data.append(v.encode('utf-8') if isinstance(v, unicode) else v)
    data.append('--%s--\r\n' % boundary)
    return '\r\n'.join(data), boundary

_CONTENT_TYPES = { '.png': 'image/png', '.gif': 'image/gif', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.jpe': 'image/jpeg' }

def _guess_content_type(ext):
    return _CONTENT_TYPES.get(ext, 'application/octet-stream')

_HTTP_GET = 0
_HTTP_POST = 1
_HTTP_UPLOAD = 2

def _http_get(url, authorization=None, **kw):
    logging.info('GET %s' % url)
    return _http_call(url, _HTTP_GET, authorization, **kw)

def _http_post(url, authorization=None, **kw):
    logging.info('POST %s' % url)
    return _http_call(url, _HTTP_POST, authorization, **kw)

def _http_upload(url, authorization=None, **kw):
    logging.info('MULTIPART POST %s' % url)
    return _http_call(url, _HTTP_UPLOAD, authorization, **kw)
class WeiboRequestFail(Exception):
    def __init__(self,httpcode,msg):
        self.httpcode=httpcode
        self.msg=msg
        try:
            self.error_data=json.decode(msg)
        except Exception,e:
            print e
            self.error_data={}
    def __str__(self):
        return '%d %s'%(self.httpcode,self.msg)

def _http_call(url, method, authorization, **kw):
    '''
    send an http request and expect to return a json object if no error.
    '''
    global InterfaceIP
    global API_RemoteIP
    params = None
    boundary = None
    if method==_HTTP_UPLOAD:
        params, boundary = _encode_multipart(**kw)
    else:
        params = _encode_params(**kw)
    urlpart=urlparse.urlparse(url)
    http_path = '%s?%s' % (urlpart.path, params) if method==_HTTP_GET else urlpart.path
    http_body = None if method==_HTTP_GET else params
    httpheaders={"Host": urlpart.netloc,
                "Accept-Encoding":"gzip"}
    if authorization:
        httpheaders['Authorization']='OAuth2 %s' % authorization
    if API_RemoteIP:
        httpheaders['API-RemoteIP']=API_RemoteIP
    if boundary:
        httpheaders['Content-Type']='multipart/form-data; boundary=%s' % boundary
    if method==_HTTP_POST and http_body is not None:
        httpheaders["Content-Type"]="application/x-www-form-urlencoded"

    source_addr=None
    if InterfaceIP is not None:
        if isinstance(InterfaceIP,list) and len(InterfaceIP)>0:
            source_addr=InterfaceIP[random.randint(0,len(InterfaceIP)-1)]
        elif (isinstance(InterfaceIP,str) or isinstance(InterfaceIP,unicode)) and len(InterfaceIP)>0:
            source_addr=InterfaceIP

    conn = httplib.HTTPSConnection(urlpart.netloc,source_address=(source_addr,0) if source_addr is not None else None ,timeout=20)
    conn.request('POST' if method==_HTTP_POST else 'GET', http_path, headers =httpheaders
                ,body=http_body)

    res = conn.getresponse()
    resbody=res.read()
    if res.getheader('Content-Encoding')=='gzip':
        resbody=gzip.GzipFile(mode='rb',fileobj=StringIO(resbody)).read()
    r = json.loads(resbody)
    if 'error_code' in r:
        raise APIError(r['error_code'], r.get('error', ''),r.get('request', ''))
    return r

class HttpObject(object):

    def __init__(self, client, method):
        self.client = client
        self.method = method

    def __getattr__(self, attr):
        def wrap(**kw):
            return _http_call('%s%s.json' % (self.client.api_url, attr.replace('__', '/')), self.method, self.client.access_token, **kw)
        return wrap

class APIClient(object):
    '''
    API client using synchronized invocation.
    '''
    def __init__(self, app_key, app_secret, redirect_uri=None, response_type='code', domain='api.weibo.com', version='2'):
        self.client_id = app_key
        self.client_secret = app_secret
        self.redirect_uri = redirect_uri
        self.response_type = response_type
        self.auth_url = 'https://%s/oauth2/' % domain
        self.api_url = 'https://%s/%s/' % (domain, version)
        self.access_token = None
        self.expires = 0.0
        self.get = HttpObject(self, _HTTP_GET)
        self.post = HttpObject(self, _HTTP_POST)
        self.upload = HttpObject(self, _HTTP_UPLOAD)

    def set_access_token(self, access_token, expires_in):
        self.access_token = str(access_token)
        self.expires = float(expires_in)

    def get_authorize_url(self, redirect_uri=None, display='default'):
        '''
        return the authroize url that should be redirect.
        '''
        redirect = redirect_uri if redirect_uri else self.redirect_uri
        if not redirect:
            raise APIError('21305', 'Parameter absent: redirect_uri', 'OAuth2 request')
        return '%s%s?%s' % (self.auth_url, 'authorize', \
                _encode_params(client_id = self.client_id, \
                        response_type = 'code', \
                        display = display, \
                        redirect_uri = redirect))

    def request_access_token(self, code, redirect_uri=None):
        '''
        return access token as object: {"access_token":"your-access-token","expires_in":12345678}, expires_in is standard unix-epoch-time
        '''
        redirect = redirect_uri if redirect_uri else self.redirect_uri
        if not redirect:
            raise APIError('21305', 'Parameter absent: redirect_uri', 'OAuth2 request')
        r = _http_post('%s%s' % (self.auth_url, 'access_token'), \
                client_id = self.client_id, \
                client_secret = self.client_secret, \
                redirect_uri = redirect, \
                code = code, grant_type = 'authorization_code')
        r['expires_in'] += int(time.time())
        return r

    def is_expires(self):
        return not self.access_token or time.time() > self.expires

    def __getattr__(self, attr):
        return getattr(self.get, attr)