# This file is part of the musicbrainzngs library
# Copyright (C) Alastair Porter, Adrian Sampson, and others
# This file is distributed under a BSD-2-Clause type license.
# See the COPYING file for more information.

import json
import re
import threading
import time
import logging
import urllib.parse
import xml.etree.ElementTree as etree
from xml.parsers import expat
from warnings import warn

import requests
from requests.auth import HTTPDigestAuth
from requests.packages.urllib3.util.retry import Retry

from musicbrainzngs import mbxml
from musicbrainzngs import util
from musicbrainzngs.version import version as _version

_log = logging.getLogger("musicbrainzngs")
_max_retries = 8

_timeout = 60
_retry = Retry(total=_max_retries, backoff_factor=2, status_forcelist=[500, 502, 503])

LUCENE_SPECIAL = r'([+\-&|!(){}\[\]\^"~*?:\\\/])'

# Constants for validation.

RELATABLE_TYPES = ['area', 'artist', 'label', 'place', 'event', 'recording', 'release', 'release-group', 'series', 'url', 'work', 'instrument']
RELATION_INCLUDES = [f'{entity}-rels' for entity in RELATABLE_TYPES]
TAG_INCLUDES = ["tags", "user-tags", "genres", "user-genres"]
RATING_INCLUDES = ["ratings", "user-ratings"]

VALID_INCLUDES = {
    'area' : ["aliases", "annotation"] + RELATION_INCLUDES + TAG_INCLUDES,
    'artist': [
        "recordings", "releases", "release-groups", "works", # Subqueries
        "various-artists", "discids", "media", "isrcs",
        "aliases", "annotation"
    ] + RELATION_INCLUDES + TAG_INCLUDES + RATING_INCLUDES,
    'annotation': [

    ],
    'instrument': ["aliases", "annotation"
    ] + RELATION_INCLUDES + TAG_INCLUDES,
    'label': [
        "releases", # Subqueries
        "discids", "media",
        "aliases", "annotation"
    ] + RELATION_INCLUDES + TAG_INCLUDES + RATING_INCLUDES,
    'place' : ["aliases", "annotation"] + RELATION_INCLUDES + TAG_INCLUDES,
    'event' : ["aliases"] + RELATION_INCLUDES + TAG_INCLUDES + RATING_INCLUDES,
    'recording': [
        "artists", "releases", # Subqueries
        "discids", "media", "artist-credits", "isrcs",
        "work-level-rels", "annotation", "aliases"
    ] + TAG_INCLUDES + RATING_INCLUDES + RELATION_INCLUDES,
    'release': [
        "artists", "labels", "recordings", "release-groups", "media",
        "artist-credits", "discids", "isrcs",
        "recording-level-rels", "work-level-rels", "annotation", "aliases"
    ] + TAG_INCLUDES + RELATION_INCLUDES,
    'release-group': [
        "artists", "releases", "discids", "media",
        "artist-credits", "annotation", "aliases"
    ] + TAG_INCLUDES + RATING_INCLUDES + RELATION_INCLUDES,
    'series': [
        "annotation", "aliases"
    ] + RELATION_INCLUDES + TAG_INCLUDES,
    'work': [
        "aliases", "annotation"
    ] + TAG_INCLUDES + RATING_INCLUDES + RELATION_INCLUDES,
    'url': RELATION_INCLUDES,
    'discid': [ # Discid should be the same as release
        "artists", "labels", "recordings", "release-groups", "media",
        "artist-credits", "discids", "isrcs",
        "recording-level-rels", "work-level-rels", "annotation", "aliases"
    ] + RELATION_INCLUDES,
    'isrc': ["artists", "releases", "isrcs"],
    'iswc': ["artists"],
    'collection': ['releases'],
}
VALID_BROWSE_INCLUDES = {
    'artist': ["aliases"] + TAG_INCLUDES + RATING_INCLUDES + RELATION_INCLUDES,
    'event': ["aliases"] + TAG_INCLUDES + RATING_INCLUDES + RELATION_INCLUDES,
    'label': ["aliases"] + TAG_INCLUDES + RATING_INCLUDES + RELATION_INCLUDES,
    'recording': ["artist-credits", "isrcs", "work-level-rels"] + TAG_INCLUDES + RATING_INCLUDES + RELATION_INCLUDES,
    'release': ["artist-credits", "labels", "recordings", "isrcs",
                "release-groups", "media", "discids"] + RELATION_INCLUDES,
    'place': ["aliases"] + TAG_INCLUDES + RELATION_INCLUDES,
    'release-group': ["artist-credits"] + TAG_INCLUDES + RATING_INCLUDES + RELATION_INCLUDES,
    'url': RELATION_INCLUDES,
    'work': ["aliases", "annotation"] + TAG_INCLUDES + RATING_INCLUDES + RELATION_INCLUDES,
}

#: These can be used to filter whenever releases are includes or browsed
VALID_RELEASE_TYPES = [
    "nat",
    "album", "single", "ep", "broadcast", "other", # primary types
    "compilation", "soundtrack", "spokenword", "interview", "audiobook",
    "live", "remix", "dj-mix", "mixtape/street", "audio drama" # secondary types
]
#: These can be used to filter whenever releases or release-groups are involved
VALID_RELEASE_STATUSES = ["official", "promotion", "bootleg", "pseudo-release"]
VALID_SEARCH_FIELDS = {
    'annotation': [
        'entity', 'name', 'text', 'type'
    ],
    'area': [
        'aid', 'alias', 'area', 'areaaccent', 'begin', 'comment', 'end',
        'ended', 'iso', 'iso1', 'iso2', 'iso3', 'sortname', 'tag', 'type'
    ],
    'artist': [
        'alias', 'area', 'arid', 'artist', 'artistaccent', 'begin', 'beginarea',
        'comment', 'country', 'end', 'endarea', 'ended', 'gender',
        'ipi', 'isni', 'primary_alias', 'sortname', 'tag', 'type'
    ],
    'event': [
        'aid', 'alias', 'area', 'arid', 'artist', 'begin', 'comment', 'eid',
        'end', 'ended', 'event', 'eventaccent', 'pid', 'place', 'tag', 'type'
    ],
    'instrument': [
        'alias', 'comment', 'description', 'iid', 'instrument',
        'instrumentaccent', 'tag', 'type'
    ],
    'label': [
        'alias', 'area', 'begin', 'code', 'comment', 'country', 'end', 'ended',
        'ipi', 'label', 'labelaccent', 'laid', 'release_count', 'sortname',
        'tag', 'type'
    ],
    'place': [
        'address', 'alias', 'area', 'begin', 'comment', 'end', 'ended', 'lat', 'long',
        'pid', 'place', 'placeaccent', 'type'
    ],
    'recording': [
        'alias', 'arid', 'artist', 'artistname', 'comment', 'country',
        'creditname', 'date', 'dur', 'format', 'isrc', 'number', 'position',
        'primarytype', 'qdur', 'recording', 'recordingaccent', 'reid',
        'release', 'rgid', 'rid', 'secondarytype', 'status', 'tag', 'tid',
        'tnum', 'tracks', 'tracksrelease', 'type', 'video'],

    'release-group': [
        'alias', 'arid', 'artist', 'artistname', 'comment', 'creditname',
        'primarytype', 'reid', 'release', 'releasegroup', 'releasegroupaccent',
        'releases', 'rgid', 'secondarytype', 'status', 'tag', 'type'
    ],
    'release': [
        'alias', 'arid', 'artist', 'artistname', 'asin', 'barcode', 'catno',
        'comment', 'country', 'creditname', 'date', 'discids', 'discidsmedium',
        'format', 'label', 'laid', 'lang', 'mediums', 'primarytype', 'quality',
        'reid', 'release', 'releaseaccent', 'rgid', 'script', 'secondarytype',
        'status', 'tag', 'tracks', 'tracksmedium', 'type'
    ],
    'series': [
        'alias', 'comment', 'orderingattribute', 'series', 'seriesaccent',
        'sid', 'tag', 'type'
    ],
    'work': [
        'alias', 'arid', 'artist', 'comment', 'iswc', 'lang', 'recording',
        'recording_count', 'rid', 'tag', 'type', 'wid', 'work', 'workaccent'
    ]
}

class AUTH_YES: pass
class AUTH_NO: pass
class AUTH_IFSET: pass
AUTH_REQUIRED_INCLUDES = ["user-tags", "user-ratings", "user-genres"]


class MusicBrainzError(Exception):
	"""Base class for all exceptions related to MusicBrainz."""
	pass

class UsageError(MusicBrainzError):
	"""Error related to misuse of the module API."""
	pass

class InvalidSearchFieldError(UsageError):
	pass

class InvalidIncludeError(UsageError):
	def __init__(self, msg='Invalid Includes', reason=None):
		super(InvalidIncludeError, self).__init__(self)
		self.msg = msg
		self.reason = reason

	def __str__(self):
		return self.msg

class InvalidFilterError(UsageError):
	def __init__(self, msg='Invalid Includes', reason=None):
		super(InvalidFilterError, self).__init__(self)
		self.msg = msg
		self.reason = reason

	def __str__(self):
		return self.msg

class WebServiceError(MusicBrainzError):
	"""Error related to MusicBrainz API requests."""
	def __init__(self, message=None, cause=None):
		"""Pass ``cause`` if this exception was caused by another
		exception.
		"""
		self.message = message
		self.cause = cause

	def __str__(self):
		if self.message:
			msg = f"{self.message}, "
		else:
			msg = ""
		msg += f"caused by: {str(self.cause)}"
		return msg

class NetworkError(WebServiceError):
	"""Problem communicating with the MB server."""
	pass

class ResponseError(WebServiceError):
	"""Bad response sent by the MB server."""
	pass

class AuthenticationError(WebServiceError):
	"""Received a HTTP 401 response while accessing a protected resource."""
	pass


# Helpers for validating and formatting allowed sets.

def _check_includes_impl(includes, valid_includes):
    for i in includes:
        if i not in valid_includes:
            raise InvalidIncludeError("Bad includes: "
                                      "%s is not a valid include" % i)
def _check_includes(entity, inc):
    _check_includes_impl(inc, VALID_INCLUDES[entity])

def _check_filter(values, valid):
	for v in values:
		if v not in valid:
			raise InvalidFilterError(v)

def _check_filter_and_make_params(entity, includes, release_status=None, release_type=None):
	"""Check that the status or type values are valid. Then, check that
    the filters can be used with the given includes. Return a params
    dict that can be passed to _do_mb_query.
    """
	if release_status is None:
		release_status = []
	if release_type is None:
		release_type = []
	if isinstance(release_status, (str, bytes)):
	    release_status = [release_status]
	if isinstance(release_type, (str, bytes)):
	    release_type = [release_type]
	_check_filter(release_status, VALID_RELEASE_STATUSES)
	_check_filter(release_type, VALID_RELEASE_TYPES)

	if (release_status
	        and "releases" not in includes and entity != "release"):
	    raise InvalidFilterError("Can't have a status with no release include")
	if (release_type
	        and "release-groups" not in includes and "releases" not in includes
	        and entity not in ["release-group", "release"]):
	    raise InvalidFilterError("Can't have a release type "
	            "with no releases or release-groups involved")

	# Build parameters.
	params = {}
	if len(release_status):
	    params["status"] = "|".join(release_status)
	if len(release_type):
	    params["type"] = "|".join(release_type)
	return params

def _docstring_get(entity):
    includes = list(VALID_INCLUDES.get(entity, []))
    return _docstring_impl("includes", includes)

def _docstring_browse(entity):
    includes = list(VALID_BROWSE_INCLUDES.get(entity, []))
    return _docstring_impl("includes", includes)

def _docstring_search(entity):
    search_fields = list(VALID_SEARCH_FIELDS.get(entity, []))
    return _docstring_impl("fields", search_fields)

def _docstring_impl(name, values):
    def _decorator(func):
        vstr = ", ".join(values)
        args = {name: vstr}
        if func.__doc__:
            func.__doc__ = func.__doc__.format(**args)
        return func

    return _decorator


# Global authentication and endpoint details.

user = password = ""
hostname = "musicbrainz.org"
https = True
_client = ""
_useragent = ""

def auth(u, p):
	"""Set the username and password to be used in subsequent queries to
	the MusicBrainz XML API that require authentication.
	"""
	global user, password
	user = u
	password = p

def set_useragent(app, version, contact=None):
	"""Set the User-Agent to be used for requests to the MusicBrainz webservice.
    This must be set before requests are made."""
	global _useragent, _client
	if not app or not version:
	    raise ValueError("App and version can not be empty")
	if contact is not None:
		_useragent = f"{app}/{version} python-musicbrainzngs/{_version} ( {contact} )"
	else:
		_useragent = f"{app}/{version} python-musicbrainzngs/{_version}"
	_client = f"{app}-{version}"
	_log.debug(f"set user-agent to {_useragent}")


def set_hostname(new_hostname, use_https=False):
    """Set the hostname for MusicBrainz webservice requests.
    Defaults to 'musicbrainz.org', accessing over https.
    For backwards compatibility, `use_https` is False by default.

    :param str new_hostname: The hostname (and port) of the MusicBrainz server to connect to
    :param bool use_https: `True` if the host should be accessed using https. Default is `False`

    Specify a non-standard port by adding it to the hostname,
    for example 'localhost:8000'."""
    global hostname
    global https
    hostname = new_hostname
    https = use_https

# Rate limiting.

limit_interval = 1.0
limit_requests = 1
do_rate_limit = True

def set_rate_limit(limit_or_interval=1.0, new_requests=1):
    """Sets the rate limiting behavior of the module. Must be invoked
    before the first Web service call.
    If the `limit_or_interval` parameter is set to False then
    rate limiting will be disabled. If it is a number then only
    a set number of requests (`new_requests`) will be made per
    given interval (`limit_or_interval`).
    """
    global limit_interval
    global limit_requests
    global do_rate_limit
    if isinstance(limit_or_interval, bool):
        do_rate_limit = limit_or_interval
    else:
        if limit_or_interval <= 0.0:
            raise ValueError("limit_or_interval can't be less than 0")
        if new_requests <= 0:
            raise ValueError("new_requests can't be less than 0")
        do_rate_limit = True
        limit_interval = limit_or_interval
        limit_requests = new_requests

class _rate_limit(object):
    """A decorator that limits the rate at which the function may be
    called. The rate is controlled by the `limit_interval` and
    `limit_requests` global variables.  The limiting is thread-safe;
    only one thread may be in the function at a time (acts like a
    monitor in this sense). The globals must be set before the first
    call to the limited function.
    """
    def __init__(self, fun):
        self.fun = fun
        self.last_call = 0.0
        self.lock = threading.Lock()
        self.remaining_requests = None # Set on first invocation.

    def _update_remaining(self):
        """Update remaining requests based on the elapsed time since
        they were last calculated.
        """
        # On first invocation, we have the maximum number of requests
        # available.
        if self.remaining_requests is None:
            self.remaining_requests = float(limit_requests)

        else:
            since_last_call = time.time() - self.last_call
            self.remaining_requests += since_last_call * \
                                       (limit_requests / limit_interval)
            self.remaining_requests = min(self.remaining_requests,
                                          float(limit_requests))

        self.last_call = time.time()

    def __call__(self, *args, **kwargs):
        with self.lock:
            if do_rate_limit:
                self._update_remaining()

                # Delay if necessary.
                while self.remaining_requests < 0.999:
                    time.sleep((1.0 - self.remaining_requests) *
                               (limit_requests / limit_interval))
                    self._update_remaining()

                # Call the original function, "paying" for this call.
                self.remaining_requests -= 1.0
            return self.fun(*args, **kwargs)

# Core (internal) functions for calling the MB API.

def _safe_read(request):
	"""
    :param request:
    """
	    # Make request (with retries).
	with requests.Session() as session:
		adapter = requests.adapters.HTTPAdapter(max_retries=_retry)
		session.mount('http://', adapter)
		session.mount('https://', adapter)
		try:
			resp = session.send(request.prepare(), allow_redirects=True, timeout=_timeout)
			resp.raise_for_status()
			return resp
		except requests.HTTPError as exc:
			if exc.response.status_code == 401:
				raise AuthenticationError(cause=exc) from exc
			raise ResponseError(cause=exc) from exc
		except requests.RequestException as exc:
			raise NetworkError(cause=exc) from exc

# Get the XML parsing exceptions to catch. The behavior chnaged with Python 2.7
# and ElementTree 1.3.
if hasattr(etree, 'ParseError'):
	ETREE_EXCEPTIONS = (etree.ParseError, expat.ExpatError)
else:
	ETREE_EXCEPTIONS = (expat.ExpatError)


# Parsing setup

def mb_parser_null(resp):
    """Return the raw response (XML)"""
    return resp

def mb_parser_xml(resp):
	"""Return a Python dict representing the XML response"""
	    # Parse the response.
	try:
		return mbxml.parse_message(resp)
	except UnicodeError as exc:
		raise ResponseError(cause=exc) from exc
	except Exception as exc:
		if isinstance(exc, ETREE_EXCEPTIONS):
			raise ResponseError(cause=exc) from exc
		else:
			raise

# Defaults
parser_fun = mb_parser_xml
ws_format = "xml"

def set_parser(new_parser_fun=None):
    """Sets the function used to parse the response from the
    MusicBrainz web service.

    If no parser is given, the parser is reset to the default parser
    :func:`mb_parser_xml`.
    """
    global parser_fun
    if new_parser_fun is None:
        new_parser_fun = mb_parser_xml
    if not callable(new_parser_fun):
        raise ValueError("new_parser_fun must be callable")
    parser_fun = new_parser_fun

def set_format(fmt="xml"):
	"""Sets the format that should be returned by the Web Service.
    The server currently supports `xml` and `json`.

    This method will set a default parser for the specified format,
    but you can modify it with :func:`set_parser`.

    .. warning:: The json format used by the server is different from
        the json format returned by the `musicbrainzngs` internal parser
        when using the `xml` format! This format may change at any time.
    """
	global ws_format
	if fmt == "xml":
		ws_format = fmt
		set_parser() # set to default
	elif fmt == "json":
	    ws_format = fmt
	    warn("The json format is non-official and may change at any time")
	    set_parser(json.loads)
	else:
		raise ValueError(f"invalid format: {fmt}")


@_rate_limit
def _mb_request(path, method='GET', auth_required=AUTH_NO,
                client_required=False, args=None, data=None, body=None):
	"""Makes a request for the specified `path` (endpoint) on /ws/2 on
    the globally-specified hostname. Parses the responses and returns
    the resulting object.  `auth_required` and `client_required` control
    whether exceptions should be raised if the username/password and
    client are left unspecified, respectively.
    """
	global parser_fun

	if args is None:
	    args = {}
	else:
	    args = dict(args) or {}

	if _useragent == "":
	    raise UsageError("set a proper user-agent with "
	                     "set_useragent(\"application name\", \"application version\", \"contact info (preferably URL or email for your application)\")")

	if client_required:
	    args["client"] = _client

	if ws_format != "xml":
	    args["fmt"] = ws_format

	headers = {
	    "User-Agent": _useragent
	}

	if body:
	    headers['Content-Type'] = 'application/xml; charset=UTF-8'
	else:
	    # Explicitly indicate zero content length if no request data
	    # will be sent (avoids HTTP 411 error).
	    headers['Content-Length'] = '0'

	# Convert args from a dictionary to a list of tuples
	# so that the ordering of elements is stable for easy
	# testing (in this case we order alphabetically)
	# Encode Unicode arguments using UTF-8.
	newargs = []
	for key, value in sorted(args.items()):
	    if isinstance(value, str):
	        value = value.encode('utf8')
	    newargs.append((key, value))

	    # Construct the full URL for the request, including hostname and
	    # query string.
	url = urllib.parse.urlunparse(
		(
			'https' if https else 'http',
			hostname,
			f'/ws/2/{path}',
			'',
			urllib.parse.urlencode(newargs),
			'',
		)
	)

	# Add credentials if required.
	add_auth = False
	if auth_required == AUTH_YES:
		_log.debug(f"Auth required for {url}")
		if not user:
		    raise UsageError("authorization required; "
		                     "use auth(user, pass) first")
		add_auth = True

	if auth_required == AUTH_IFSET and user:
		_log.debug(f"Using auth for {url} because user and pass is set")
		add_auth = True

	if add_auth:
	    auth_handler = HTTPDigestAuth(user, password)
	else:
	    auth_handler = None

	allowed_m = ["GET", "POST", "DELETE", "PUT"]
	if method not in allowed_m:
		raise ValueError(f"invalid method: {method}")

	req = requests.Request(
	    method,
	    url,
	    auth=auth_handler,
	    headers=headers,
	    data=body,
	)

	resp = _safe_read(req)

	return parser_fun(resp.content)


def _get_auth_type(entity, id, includes):
    """ Some calls require authentication. This returns
    a constant (Yes, No, IfSet) for the auth status of the call.
    """
    if "user-tags" in includes or "user-ratings" in includes or "user-genres" in includes:
        return AUTH_YES
    elif entity.startswith("collection"):
        if not id:
            return AUTH_YES
        else:
            return AUTH_IFSET
    else:
        return AUTH_NO


def _do_mb_query(entity, id, includes=None, params=None):
	"""Make a single GET call to the MusicBrainz XML API. `entity` is a
	string indicated the type of object to be retrieved. The id may be
	empty, in which case the query is a search. `includes` is a list
	of strings that must be valid includes for the entity type. `params`
	is a dictionary of additional parameters for the API call. The
	response is parsed and returned.
	"""
	if includes is None:
		includes = []
	if params is None:
		params = {}
	# Build arguments.
	if not isinstance(includes, list):
		includes = [includes]
	_check_includes(entity, includes)
	auth_required = _get_auth_type(entity, id, includes)
	args = dict(params)
	if len(includes) > 0:
		inc = " ".join(includes)
		args["inc"] = inc

	# Build the endpoint components.
	path = f'{entity}/{id}'
	return _mb_request(path, 'GET', auth_required, args=args)

def _do_mb_search(entity, query='', fields=None, limit=None, offset=None, strict=False):
	"""Perform a full-text search on the MusicBrainz search server.
	`query` is a lucene query string when no fields are set,
	but is escaped when any fields are given. `fields` is a dictionary
	of key/value query parameters. They keys in `fields` must be valid
	for the given entity type.
	"""
	if fields is None:
		fields = {}
	# Encode the query terms as a Lucene query string.
	query_parts = []
	if query:
		clean_query = util._unicode(query)
		if fields:
			clean_query = re.sub(LUCENE_SPECIAL, r'\\\1',
					     clean_query)
			if strict:
				query_parts.append(f'"{clean_query}"')
			else:
				query_parts.append(clean_query.lower())
		else:
			query_parts.append(clean_query)
	for key, value in fields.items():
		# Ensure this is a valid search field.
		if key not in VALID_SEARCH_FIELDS[entity]:
			raise InvalidSearchFieldError(
				f'{key} is not a valid search field for {entity}'
			)

		# Escape Lucene's special characters.
		value = util._unicode(value)
		if value := re.sub(LUCENE_SPECIAL, r'\\\1', value):
			if strict:
				query_parts.append(f'{key}:"{value}"')
			else:
				value = value.lower() # avoid AND / OR
				query_parts.append(f'{key}:({value})')
	if strict:
		full_query = ' AND '.join(query_parts).strip()
	else:
		full_query = ' '.join(query_parts).strip()

	if not full_query:
		raise ValueError('at least one query term is required')

	# Additional parameters to the search.
	params = {'query': full_query}
	if limit:
		params['limit'] = str(limit)
	if offset:
		params['offset'] = str(offset)

	return _do_mb_query(entity, '', [], params)

def _do_mb_delete(path):
	"""Send a DELETE request for the specified object.
	"""
	return _mb_request(path, 'DELETE', AUTH_YES, True)

def _do_mb_put(path):
	"""Send a PUT request for the specified object.
	"""
	return _mb_request(path, 'PUT', AUTH_YES, True)

def _do_mb_post(path, body):
	"""Perform a single POST call for an endpoint with a specified
	request body.
	"""
	return _mb_request(path, 'POST', AUTH_YES, True, body=body)


# The main interface!

# Single entity by ID

@_docstring_get("area")
def get_area_by_id(id, includes=None, release_status=None, release_type=None):
	"""Get the area with the MusicBrainz `id` as a dict with an 'area' key.

    *Available includes*: {includes}"""
	if includes is None:
		includes = []
	if release_status is None:
		release_status = []
	if release_type is None:
		release_type = []
	params = _check_filter_and_make_params("area", includes,
	                                       release_status, release_type)
	return _do_mb_query("area", id, includes, params)

@_docstring_get("artist")
def get_artist_by_id(id, includes=None, release_status=None, release_type=None):
	"""Get the artist with the MusicBrainz `id` as a dict with an 'artist' key.

    *Available includes*: {includes}"""
	if includes is None:
		includes = []
	if release_status is None:
		release_status = []
	if release_type is None:
		release_type = []
	params = _check_filter_and_make_params("artist", includes,
	                                       release_status, release_type)
	return _do_mb_query("artist", id, includes, params)

@_docstring_get("instrument")
def get_instrument_by_id(id, includes=None, release_status=None, release_type=None):
	"""Get the instrument with the MusicBrainz `id` as a dict with an 'artist' key.

    *Available includes*: {includes}"""
	if includes is None:
		includes = []
	if release_status is None:
		release_status = []
	if release_type is None:
		release_type = []
	params = _check_filter_and_make_params("instrument", includes,
	                                       release_status, release_type)
	return _do_mb_query("instrument", id, includes, params)

@_docstring_get("label")
def get_label_by_id(id, includes=None, release_status=None, release_type=None):
	"""Get the label with the MusicBrainz `id` as a dict with a 'label' key.

    *Available includes*: {includes}"""
	if includes is None:
		includes = []
	if release_status is None:
		release_status = []
	if release_type is None:
		release_type = []
	params = _check_filter_and_make_params("label", includes,
	                                       release_status, release_type)
	return _do_mb_query("label", id, includes, params)

@_docstring_get("place")
def get_place_by_id(id, includes=None, release_status=None, release_type=None):
	"""Get the place with the MusicBrainz `id` as a dict with an 'place' key.

    *Available includes*: {includes}"""
	if includes is None:
		includes = []
	if release_status is None:
		release_status = []
	if release_type is None:
		release_type = []
	params = _check_filter_and_make_params("place", includes,
	                                       release_status, release_type)
	return _do_mb_query("place", id, includes, params)

@_docstring_get("event")
def get_event_by_id(id, includes=None, release_status=None, release_type=None):
	"""Get the event with the MusicBrainz `id` as a dict with an 'event' key.

    The event dict has the following keys:
    `id`, `type`, `name`, `time`, `disambiguation` and `life-span`.

    *Available includes*: {includes}"""
	if includes is None:
		includes = []
	if release_status is None:
		release_status = []
	if release_type is None:
		release_type = []
	params = _check_filter_and_make_params("event", includes,
	                                       release_status, release_type)
	return _do_mb_query("event", id, includes, params)

@_docstring_get("recording")
def get_recording_by_id(id, includes=None, release_status=None, release_type=None):
	"""Get the recording with the MusicBrainz `id` as a dict
    with a 'recording' key.

    *Available includes*: {includes}"""
	if includes is None:
		includes = []
	if release_status is None:
		release_status = []
	if release_type is None:
		release_type = []
	params = _check_filter_and_make_params("recording", includes,
	                                       release_status, release_type)
	return _do_mb_query("recording", id, includes, params)

@_docstring_get("release")
def get_release_by_id(id, includes=None, release_status=None, release_type=None):
	"""Get the release with the MusicBrainz `id` as a dict with a 'release' key.

    *Available includes*: {includes}"""
	if includes is None:
		includes = []
	if release_status is None:
		release_status = []
	if release_type is None:
		release_type = []
	params = _check_filter_and_make_params("release", includes,
	                                       release_status, release_type)
	return _do_mb_query("release", id, includes, params)

@_docstring_get("release-group")
def get_release_group_by_id(id, includes=None, release_status=None, release_type=None):
	"""Get the release group with the MusicBrainz `id` as a dict
    with a 'release-group' key.

    *Available includes*: {includes}"""
	if includes is None:
		includes = []
	if release_status is None:
		release_status = []
	if release_type is None:
		release_type = []
	params = _check_filter_and_make_params("release-group", includes,
	                                       release_status, release_type)
	return _do_mb_query("release-group", id, includes, params)

@_docstring_get("series")
def get_series_by_id(id, includes=None):
	"""Get the series with the MusicBrainz `id` as a dict with a 'series' key.

    *Available includes*: {includes}"""
	if includes is None:
		includes = []
	return _do_mb_query("series", id, includes)

@_docstring_get("work")
def get_work_by_id(id, includes=None):
	"""Get the work with the MusicBrainz `id` as a dict with a 'work' key.

    *Available includes*: {includes}"""
	if includes is None:
		includes = []
	return _do_mb_query("work", id, includes)

@_docstring_get("url")
def get_url_by_id(id, includes=None):
	"""Get the url with the MusicBrainz `id` as a dict with a 'url' key.

    *Available includes*: {includes}"""
	if includes is None:
		includes = []
	return _do_mb_query("url", id, includes)


# Searching

@_docstring_search("annotation")
def search_annotations(query='', limit=None, offset=None, strict=False, **fields):
    """Search for annotations and return a dict with an 'annotation-list' key.

    *Available search fields*: {fields}"""
    return _do_mb_search('annotation', query, fields, limit, offset, strict)

@_docstring_search("area")
def search_areas(query='', limit=None, offset=None, strict=False, **fields):
    """Search for areas and return a dict with an 'area-list' key.

    *Available search fields*: {fields}"""
    return _do_mb_search('area', query, fields, limit, offset, strict)

@_docstring_search("artist")
def search_artists(query='', limit=None, offset=None, strict=False, **fields):
    """Search for artists and return a dict with an 'artist-list' key.

    *Available search fields*: {fields}"""
    return _do_mb_search('artist', query, fields, limit, offset, strict)

@_docstring_search("event")
def search_events(query='', limit=None, offset=None, strict=False, **fields):
    """Search for events and return a dict with an 'event-list' key.

    *Available search fields*: {fields}"""
    return _do_mb_search('event', query, fields, limit, offset, strict)

@_docstring_search("instrument")
def search_instruments(query='', limit=None, offset=None, strict=False, **fields):
    """Search for instruments and return a dict with a 'instrument-list' key.

    *Available search fields*: {fields}"""
    return _do_mb_search('instrument', query, fields, limit, offset, strict)

@_docstring_search("label")
def search_labels(query='', limit=None, offset=None, strict=False, **fields):
    """Search for labels and return a dict with a 'label-list' key.

    *Available search fields*: {fields}"""
    return _do_mb_search('label', query, fields, limit, offset, strict)

@_docstring_search("place")
def search_places(query='', limit=None, offset=None, strict=False, **fields):
    """Search for places and return a dict with a 'place-list' key.

    *Available search fields*: {fields}"""
    return _do_mb_search('place', query, fields, limit, offset, strict)

@_docstring_search("recording")
def search_recordings(query='', limit=None, offset=None,
                      strict=False, **fields):
    """Search for recordings and return a dict with a 'recording-list' key.

    *Available search fields*: {fields}"""
    return _do_mb_search('recording', query, fields, limit, offset, strict)

@_docstring_search("release")
def search_releases(query='', limit=None, offset=None, strict=False, **fields):
    """Search for recordings and return a dict with a 'recording-list' key.

    *Available search fields*: {fields}"""
    return _do_mb_search('release', query, fields, limit, offset, strict)

@_docstring_search("release-group")
def search_release_groups(query='', limit=None, offset=None,
			  strict=False, **fields):
    """Search for release groups and return a dict
    with a 'release-group-list' key.

    *Available search fields*: {fields}"""
    return _do_mb_search('release-group', query, fields, limit, offset, strict)

@_docstring_search("series")
def search_series(query='', limit=None, offset=None, strict=False, **fields):
    """Search for series and return a dict with a 'series-list' key.

    *Available search fields*: {fields}"""
    return _do_mb_search('series', query, fields, limit, offset, strict)

@_docstring_search("work")
def search_works(query='', limit=None, offset=None, strict=False, **fields):
    """Search for works and return a dict with a 'work-list' key.

    *Available search fields*: {fields}"""
    return _do_mb_search('work', query, fields, limit, offset, strict)


# Lists of entities
@_docstring_get("discid")
def get_releases_by_discid(id, includes=None, toc=None, cdstubs=True, media_format=None):
	"""Search for releases with a :musicbrainz:`Disc ID` or table of contents.

    When a `toc` is provided and no release with the disc ID is found,
    a fuzzy search by the toc is done.
    The `toc` should have to same format as :attr:`discid.Disc.toc_string`.
    When a `toc` is provided, the format of the discid itself is not
    checked server-side, so any value may be passed if searching by only
    `toc` is desired.

    If no toc matches in musicbrainz but a :musicbrainz:`CD Stub` does,
    the CD Stub will be returned. Prevent this from happening by
    passing `cdstubs=False`.

    By default only results that match a format that allows discids
    (e.g. CD) are included. To include all media formats, pass
    `media_format='all'`.

    The result is a dict with either a 'disc' , a 'cdstub' key
    or a 'release-list' (fuzzy match with TOC).
    A 'disc' has an 'offset-count', an 'offset-list' and a 'release-list'.
    A 'cdstub' key has direct 'artist' and 'title' keys.

    *Available includes*: {includes}"""
	if includes is None:
		includes = []
	params = _check_filter_and_make_params("discid", includes, release_status=[],
	                                       release_type=[])
	if toc:
	    params["toc"] = toc
	if not cdstubs:
	    params["cdstubs"] = "no"
	if media_format:
	    params["media-format"] = media_format
	return _do_mb_query("discid", id, includes, params)


@_docstring_get("recording")
def get_recordings_by_isrc(isrc, includes=None, release_status=None, release_type=None):
	"""Search for recordings with an :musicbrainz:`ISRC`.
    The result is a dict with an 'isrc' key,
    which again includes a 'recording-list'.

    *Available includes*: {includes}"""
	if includes is None:
		includes = []
	if release_status is None:
		release_status = []
	if release_type is None:
		release_type = []
	params = _check_filter_and_make_params("isrc", includes,
	                                       release_status, release_type)
	return _do_mb_query("isrc", isrc, includes, params)

@_docstring_get("work")
def get_works_by_iswc(iswc, includes=None):
	"""Search for works with an :musicbrainz:`ISWC`.
    The result is a dict with a`work-list`.

    *Available includes*: {includes}"""
	if includes is None:
		includes = []
	return _do_mb_query("iswc", iswc, includes)


def _browse_impl(entity, includes, limit, offset, params, release_status=None, release_type=None):
	if release_status is None:
		release_status = []
	if release_type is None:
		release_type = []
	includes = includes if isinstance(includes, list) else [includes]
	valid_includes = VALID_BROWSE_INCLUDES[entity]
	_check_includes_impl(includes, valid_includes)
	p = {k: v for k, v in params.items() if v}
	if len(p) > 1:
	    raise Exception("Can't have more than one of " + ", ".join(params.keys()))
	if limit: p["limit"] = limit
	if offset: p["offset"] = offset
	filterp = _check_filter_and_make_params(entity, includes, release_status, release_type)
	p |= filterp
	return _do_mb_query(entity, "", includes, p)

# Browse methods
# Browse include are a subset of regular get includes, so we check them here
# and the test in _do_mb_query will pass anyway.
@_docstring_browse("artist")
def browse_artists(recording=None, release=None, release_group=None, work=None, includes=None, limit=None, offset=None):
	"""Get all artists linked to a recording, a release or a release group.
    You need to give one MusicBrainz ID.

    *Available includes*: {includes}"""
	if includes is None:
		includes = []
	params = {"recording": recording,
	          "release": release,
	          "release-group": release_group,
	          "work": work}
	return _browse_impl("artist", includes, limit, offset, params)

@_docstring_browse("event")
def browse_events(area=None, artist=None, place=None, includes=None, limit=None, offset=None):
	"""Get all events linked to a area, a artist or a place.
    You need to give one MusicBrainz ID.

    *Available includes*: {includes}"""
	if includes is None:
		includes = []
	params = {"area": area,
	          "artist": artist,
	          "place": place}
	return _browse_impl("event", includes, limit, offset, params)

@_docstring_browse("label")
def browse_labels(release=None, includes=None, limit=None, offset=None):
	"""Get all labels linked to a relase. You need to give a MusicBrainz ID.

    *Available includes*: {includes}"""
	if includes is None:
		includes = []
	params = {"release": release}
	return _browse_impl("label", includes, limit, offset, params)

@_docstring_browse("place")
def browse_places(area=None, includes=None, limit=None, offset=None):
	"""Get all places linked to an area. You need to give a MusicBrainz ID.

    *Available includes*: {includes}"""
	if includes is None:
		includes = []
	params = {"area": area}
	return _browse_impl("place", includes, limit, offset, params)

@_docstring_browse("recording")
def browse_recordings(artist=None, release=None, includes=None, limit=None, offset=None):
	"""Get all recordings linked to an artist or a release.
    You need to give one MusicBrainz ID.

    *Available includes*: {includes}"""
	if includes is None:
		includes = []
	params = {"artist": artist,
	          "release": release}
	return _browse_impl("recording", includes, limit, offset, params)

@_docstring_browse("release")
def browse_releases(artist=None, track_artist=None, label=None, recording=None, release_group=None, release_status=None, release_type=None, includes=None, limit=None, offset=None):
	"""Get all releases linked to an artist, a label, a recording
    or a release group. You need to give one MusicBrainz ID.

    You can also browse by `track_artist`, which gives all releases where some
    tracks are attributed to that artist, but not the whole release.

    You can filter by :data:`musicbrainz.VALID_RELEASE_TYPES` or
    :data:`musicbrainz.VALID_RELEASE_STATUSES`.

    *Available includes*: {includes}"""
	if release_status is None:
		release_status = []
	if release_type is None:
		release_type = []
	if includes is None:
		includes = []
	# track_artist param doesn't work yet
	params = {"artist": artist,
	          "track_artist": track_artist,
	          "label": label,
	          "recording": recording,
	          "release-group": release_group}
	return _browse_impl("release", includes, limit, offset,
	                    params, release_status, release_type)

@_docstring_browse("release-group")
def browse_release_groups(artist=None, release=None, release_type=None, includes=None, limit=None, offset=None):
	"""Get all release groups linked to an artist or a release.
    You need to give one MusicBrainz ID.

    You can filter by :data:`musicbrainz.VALID_RELEASE_TYPES`.

    *Available includes*: {includes}"""
	if release_type is None:
		release_type = []
	if includes is None:
		includes = []
	params = {"artist": artist,
	          "release": release}
	return _browse_impl("release-group", includes, limit,
	                    offset, params, [], release_type)

@_docstring_browse("url")
def browse_urls(resource=None, includes=None, limit=None, offset=None):
	"""Get urls by actual URL string.
    You need to give a URL string as 'resource'

    *Available includes*: {includes}"""
	if includes is None:
		includes = []
	params = {"resource": resource}
	return _browse_impl("url", includes, limit, offset, params)

@_docstring_browse("work")
def browse_works(artist=None, includes=None, limit=None, offset=None):
	"""Get all works linked to an artist

    *Available includes*: {includes}"""
	if includes is None:
		includes = []
	params = {"artist": artist}
	return _browse_impl("work", includes, limit, offset, params)

# Collections
def get_collections():
    """List the collections for the currently :func:`authenticated <auth>` user
    as a dict with a 'collection-list' key."""
    # Missing <release-list count="n"> the count in the reply
    return _do_mb_query("collection", '')

def _do_collection_query(collection, collection_type, limit, offset):
	params = {}
	if limit: params["limit"] = limit
	if offset: params["offset"] = offset
	return _do_mb_query(
		"collection", f"{collection}/{collection_type}", [], params
	)

def get_artists_in_collection(collection, limit=None, offset=None):
    """List the artists in a collection.
    Returns a dict with a 'collection' key, which again has a 'artist-list'.

    See `Browsing`_ for how to use `limit` and `offset`.
    """
    return _do_collection_query(collection, "artists", limit, offset)

def get_releases_in_collection(collection, limit=None, offset=None):
    """List the releases in a collection.
    Returns a dict with a 'collection' key, which again has a 'release-list'.

    See `Browsing`_ for how to use `limit` and `offset`.
    """
    return _do_collection_query(collection, "releases", limit, offset)

def get_events_in_collection(collection, limit=None, offset=None):
    """List the events in a collection.
    Returns a dict with a 'collection' key, which again has a 'event-list'.

    See `Browsing`_ for how to use `limit` and `offset`.
    """
    return _do_collection_query(collection, "events", limit, offset)

def get_places_in_collection(collection, limit=None, offset=None):
    """List the places in a collection.
    Returns a dict with a 'collection' key, which again has a 'place-list'.

    See `Browsing`_ for how to use `limit` and `offset`.
    """
    return _do_collection_query(collection, "places", limit, offset)

def get_recordings_in_collection(collection, limit=None, offset=None):
    """List the recordings in a collection.
    Returns a dict with a 'collection' key, which again has a 'recording-list'.

    See `Browsing`_ for how to use `limit` and `offset`.
    """
    return _do_collection_query(collection, "recordings", limit, offset)

def get_works_in_collection(collection, limit=None, offset=None):
    """List the works in a collection.
    Returns a dict with a 'collection' key, which again has a 'work-list'.

    See `Browsing`_ for how to use `limit` and `offset`.
    """
    return _do_collection_query(collection, "works", limit, offset)


# Submission methods

def submit_barcodes(release_barcode):
    """Submits a set of {release_id1: barcode, ...}"""
    query = mbxml.make_barcode_request(release_barcode)
    return _do_mb_post("release", query)


def submit_isrcs(recording_isrcs):
	"""Submit ISRCs.
    Submits a set of {recording-id1: [isrc1, ...], ...}
    or {recording_id1: isrc, ...}.
    """
	rec2isrcs = {
		rec: isrcs if isinstance(isrcs, list) else [isrcs]
		for rec, isrcs in recording_isrcs.items()
	}
	query = mbxml.make_isrc_request(rec2isrcs)
	return _do_mb_post("recording", query)

def submit_tags(**kwargs):
    """Submit user tags.
    Takes parameters named e.g. 'artist_tags', 'recording_tags', etc.,
    and of the form:
    {entity_id1: [tag1, ...], ...}
    If you only have one tag for an entity you can use a string instead
    of a list.

    The user's tags for each entity will be set to that list, adding or
    removing tags as necessary. Submitting an empty list for an entity
    will remove all tags for that entity by the user.
    """
    for k, v in kwargs.items():
        for id, tags in v.items():
            kwargs[k][id] = tags if isinstance(tags, list) else [tags]

    query = mbxml.make_tag_request(**kwargs)
    return _do_mb_post("tag", query)

def submit_ratings(**kwargs):
    """Submit user ratings.
    Takes parameters named e.g. 'artist_ratings', 'recording_ratings', etc.,
    and of the form:
    {entity_id1: rating, ...}

    Ratings are numbers from 0-100, at intervals of 20 (20 per 'star').
    Submitting a rating of 0 will remove the user's rating.
    """
    query = mbxml.make_rating_request(**kwargs)
    return _do_mb_post("rating", query)

def add_releases_to_collection(collection, releases=None):
	"""Add releases to a collection.
    Collection and releases should be identified by their MBIDs
    """
	if releases is None:
		releases = []
	# XXX: Maximum URI length of 16kb means we should only allow ~400 releases
	releaselist = ";".join(releases)
	return _do_mb_put(f"collection/{collection}/releases/{releaselist}")

def remove_releases_from_collection(collection, releases=None):
	"""Remove releases from a collection.
    Collection and releases should be identified by their MBIDs
    """
	if releases is None:
		releases = []
	releaselist = ";".join(releases)
	return _do_mb_delete(f"collection/{collection}/releases/{releaselist}")
