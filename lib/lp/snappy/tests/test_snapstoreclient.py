# Copyright 2016-2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for communication with the snap store."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type

import base64
from cgi import FieldStorage
import hashlib
import io
import json

from httmock import (
    all_requests,
    HTTMock,
    urlmatch,
    )
from lazr.restful.utils import get_current_browser_request
from pymacaroons import (
    Macaroon,
    Verifier,
    )
from requests import Request
from requests.utils import parse_dict_header
from testtools.matchers import (
    Contains,
    ContainsDict,
    Equals,
    Matcher,
    MatchesDict,
    MatchesListwise,
    MatchesStructure,
    Mismatch,
    StartsWith,
    )
import transaction
from zope.component import getUtility

from lp.services.config import config
from lp.services.features.testing import FeatureFixture
from lp.services.log.logger import BufferLogger
from lp.services.memcache.interfaces import IMemcacheClient
from lp.services.timeline.requesttimeline import get_request_timeline
from lp.snappy.interfaces.snap import SNAP_TESTING_FLAGS
from lp.snappy.interfaces.snapstoreclient import (
    BadRequestPackageUploadResponse,
    BadScanStatusResponse,
    BadSearchResponse,
    ISnapStoreClient,
    ReleaseFailedResponse,
    ScanFailedResponse,
    UnauthorizedUploadResponse,
    UploadFailedResponse,
    UploadNotScannedYetResponse,
    )
from lp.snappy.model.snapstoreclient import (
    InvalidStoreSecretsError,
    MacaroonAuth,
    )
from lp.testing import (
    TestCase,
    TestCaseWithFactory,
    )
from lp.testing.dbuser import dbuser
from lp.testing.layers import LaunchpadZopelessLayer


class MacaroonsVerify(Matcher):
    """Matches if serialised macaroons pass verification."""

    def __init__(self, key):
        self.key = key

    def match(self, macaroons):
        mismatch = Contains("root").match(macaroons)
        if mismatch is not None:
            return mismatch
        root_macaroon = Macaroon.deserialize(macaroons["root"])
        if "discharge" in macaroons:
            discharge_macaroons = [
                Macaroon.deserialize(macaroons["discharge"])]
        else:
            discharge_macaroons = []
        try:
            Verifier().verify(root_macaroon, self.key, discharge_macaroons)
        except Exception as e:
            return Mismatch("Macaroons do not verify: %s" % e)


class TestMacaroonAuth(TestCase):

    def test_good(self):
        r = Request()
        root_key = hashlib.sha256("root").hexdigest()
        root_macaroon = Macaroon(key=root_key)
        discharge_key = hashlib.sha256("discharge").hexdigest()
        discharge_caveat_id = '{"secret": "thing"}'
        root_macaroon.add_third_party_caveat(
            "sso.example", discharge_key, discharge_caveat_id)
        unbound_discharge_macaroon = Macaroon(
            location="sso.example", key=discharge_key,
            identifier=discharge_caveat_id)
        MacaroonAuth(
            root_macaroon.serialize(),
            unbound_discharge_macaroon.serialize())(r)
        auth_value = r.headers["Authorization"]
        self.assertThat(auth_value, StartsWith("Macaroon "))
        self.assertThat(
            parse_dict_header(auth_value[len("Macaroon "):]),
            MacaroonsVerify(root_key))

    def test_good_no_discharge(self):
        r = Request()
        root_key = hashlib.sha256("root").hexdigest()
        root_macaroon = Macaroon(key=root_key)
        MacaroonAuth(root_macaroon.serialize())(r)
        auth_value = r.headers["Authorization"]
        self.assertThat(auth_value, StartsWith("Macaroon "))
        self.assertThat(
            parse_dict_header(auth_value[len("Macaroon "):]),
            MacaroonsVerify(root_key))

    def test_bad_framing(self):
        r = Request()
        self.assertRaises(
            InvalidStoreSecretsError, MacaroonAuth('ev"il', 'wic"ked'), r)
        # Test _makeAuthParam's behaviour directly in case somebody somehow
        # convinces Macaroon.serialize to emit data that breaks framing.
        self.assertRaises(
            InvalidStoreSecretsError, MacaroonAuth(None)._makeAuthParam,
            'ev"il', 'good')
        self.assertRaises(
            InvalidStoreSecretsError, MacaroonAuth(None)._makeAuthParam,
            'good', 'ev"il')

    def test_logging(self):
        r = Request()
        root_key = hashlib.sha256("root").hexdigest()
        root_macaroon = Macaroon(key=root_key)
        discharge_key = hashlib.sha256("discharge").hexdigest()
        discharge_caveat_id = '{"secret": "thing"}'
        root_macaroon.add_third_party_caveat(
            "sso.example", discharge_key, discharge_caveat_id)
        root_macaroon.add_first_party_caveat(
            "store.example|package_id|{}".format(
                json.dumps(["example-package"])))
        unbound_discharge_macaroon = Macaroon(
            location="sso.example", key=discharge_key,
            identifier=discharge_caveat_id)
        unbound_discharge_macaroon.add_first_party_caveat(
            "sso.example|account|{}".format(
                base64.b64encode(json.dumps({
                    "openid": "1234567",
                    "email": "user@example.org",
                    }))))
        logger = BufferLogger()
        MacaroonAuth(
            root_macaroon.serialize(),
            unbound_discharge_macaroon.serialize(), logger=logger)(r)
        self.assertEqual(
            ['DEBUG root macaroon: snap-ids: ["example-package"]',
             'DEBUG discharge macaroon: OpenID identifier: 1234567'],
            logger.getLogBuffer().splitlines())


class RequestMatches(Matcher):
    """Matches a request with the specified attributes."""

    def __init__(self, url, auth=None, json_data=None, form_data=None,
                 **kwargs):
        self.url = url
        self.auth = auth
        self.json_data = json_data
        self.form_data = form_data
        self.kwargs = kwargs

    def match(self, request):
        mismatch = MatchesStructure(url=self.url, **self.kwargs).match(request)
        if mismatch is not None:
            return mismatch
        if self.auth is not None:
            mismatch = Contains("Authorization").match(request.headers)
            if mismatch is not None:
                return mismatch
            auth_value = request.headers["Authorization"]
            auth_scheme, auth_params_matcher = self.auth
            mismatch = StartsWith(auth_scheme + " ").match(auth_value)
            if mismatch is not None:
                return mismatch
            mismatch = auth_params_matcher.match(
                parse_dict_header(auth_value[len(auth_scheme + " "):]))
            if mismatch is not None:
                return mismatch
        if self.json_data is not None:
            mismatch = Equals(self.json_data).match(json.loads(request.body))
            if mismatch is not None:
                return mismatch
        if self.form_data is not None:
            if hasattr(request.body, "read"):
                body = request.body.read()
            else:
                body = request.body
            fs = FieldStorage(
                fp=io.BytesIO(body),
                environ={"REQUEST_METHOD": request.method},
                headers=request.headers)
            mismatch = MatchesDict(self.form_data).match(fs)
            if mismatch is not None:
                return mismatch


class TestSnapStoreClient(TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    def setUp(self):
        super(TestSnapStoreClient, self).setUp()
        self.useFixture(FeatureFixture(SNAP_TESTING_FLAGS))
        self.pushConfig(
            "snappy", store_url="http://sca.example/",
            store_upload_url="http://updown.example/",
            store_search_url="http://search.example/")
        self.pushConfig(
            "launchpad", openid_provider_root="http://sso.example/")
        self.client = getUtility(ISnapStoreClient)
        self.unscanned_upload_requests = []
        self.channels = [
            {"name": "stable", "display_name": "Stable"},
            {"name": "edge", "display_name": "Edge"},
            ]

    def _make_store_secrets(self):
        self.root_key = hashlib.sha256(
            self.factory.getUniqueString()).hexdigest()
        root_macaroon = Macaroon(key=self.root_key)
        self.discharge_key = hashlib.sha256(
            self.factory.getUniqueString()).hexdigest()
        self.discharge_caveat_id = self.factory.getUniqueString()
        root_macaroon.add_third_party_caveat(
            "sso.example", self.discharge_key, self.discharge_caveat_id)
        unbound_discharge_macaroon = Macaroon(
            location="sso.example", key=self.discharge_key,
            identifier=self.discharge_caveat_id)
        return {
            "root": root_macaroon.serialize(),
            "discharge": unbound_discharge_macaroon.serialize(),
            }

    @urlmatch(path=r".*/unscanned-upload/$")
    def _unscanned_upload_handler(self, url, request):
        self.unscanned_upload_requests.append(request)
        return {
            "status_code": 200,
            "content": {"successful": True, "upload_id": 1},
            }

    @urlmatch(path=r".*/snap-push/$")
    def _snap_push_handler(self, url, request):
        self.snap_push_request = request
        return {
            "status_code": 202,
            "content": {
                "success": True,
                "status_details_url": (
                    "http://sca.example/dev/api/snaps/1/builds/1/status"),
                }}

    @urlmatch(path=r".*/api/v2/tokens/refresh$")
    def _macaroon_refresh_handler(self, url, request):
        self.refresh_request = request
        new_macaroon = Macaroon(
            location="sso.example", key=self.discharge_key,
            identifier=self.discharge_caveat_id)
        new_macaroon.add_first_party_caveat("sso|expires|tomorrow")
        return {
            "status_code": 200,
            "content": {"discharge_macaroon": new_macaroon.serialize()},
            }

    @urlmatch(path=r".*/api/v1/channels$")
    def _channels_handler(self, url, request):
        self.channels_request = request
        return {
            "status_code": 200,
            "content": {"_embedded": {"clickindex:channel": self.channels}},
            }

    @urlmatch(path=r".*/snap-release/$")
    def _snap_release_handler(self, url, request):
        self.snap_release_request = request
        return {
            "status_code": 200,
            "content": {
                "success": True,
                "channel_map": [
                    {"channel": "stable", "info": "specific",
                     "version": "1.0", "revision": 1},
                    {"channel": "edge", "info": "specific",
                     "version": "1.0", "revision": 1},
                    ],
                "opened_channels": ["stable", "edge"],
                }}

    def test_requestPackageUploadPermission(self):
        @all_requests
        def handler(url, request):
            self.request = request
            return {"status_code": 200, "content": {"macaroon": "dummy"}}

        snappy_series = self.factory.makeSnappySeries(name="rolling")
        with HTTMock(handler):
            macaroon = self.client.requestPackageUploadPermission(
                snappy_series, "test-snap")
        self.assertThat(self.request, RequestMatches(
            url=Equals("http://sca.example/dev/api/acl/"),
            method=Equals("POST"),
            json_data={
                "packages": [{"name": "test-snap", "series": "rolling"}],
                "permissions": ["package_upload"],
                }))
        self.assertEqual("dummy", macaroon)
        request = get_current_browser_request()
        start, stop = get_request_timeline(request).actions[-2:]
        self.assertEqual("request-snap-upload-macaroon-start", start.category)
        self.assertEqual("rolling/test-snap", start.detail)
        self.assertEqual("request-snap-upload-macaroon-stop", stop.category)
        self.assertEqual("rolling/test-snap", stop.detail)

    def test_requestPackageUploadPermission_missing_macaroon(self):
        @all_requests
        def handler(url, request):
            return {"status_code": 200, "content": {}}

        snappy_series = self.factory.makeSnappySeries()
        with HTTMock(handler):
            self.assertRaisesWithContent(
                BadRequestPackageUploadResponse, b"{}",
                self.client.requestPackageUploadPermission,
                snappy_series, "test-snap")

    def test_requestPackageUploadPermission_error(self):
        @all_requests
        def handler(url, request):
            return {
                "status_code": 503,
                "content": {"error_list": [{"message": "Failed"}]},
                }

        snappy_series = self.factory.makeSnappySeries()
        with HTTMock(handler):
            self.assertRaisesWithContent(
                BadRequestPackageUploadResponse, "Failed",
                self.client.requestPackageUploadPermission,
                snappy_series, "test-snap")

    def test_requestPackageUploadPermission_404(self):
        @all_requests
        def handler(url, request):
            return {"status_code": 404, "reason": b"Not found"}

        snappy_series = self.factory.makeSnappySeries()
        with HTTMock(handler):
            self.assertRaisesWithContent(
                BadRequestPackageUploadResponse,
                b"404 Client Error: Not found",
                self.client.requestPackageUploadPermission,
                snappy_series, "test-snap")

    def makeUploadableSnapBuild(self, store_secrets=None):
        if store_secrets is None:
            store_secrets = self._make_store_secrets()
        snap = self.factory.makeSnap(
            store_upload=True,
            store_series=self.factory.makeSnappySeries(name="rolling"),
            store_name="test-snap", store_secrets=store_secrets)
        snapbuild = self.factory.makeSnapBuild(snap=snap)
        snap_lfa = self.factory.makeLibraryFileAlias(
            filename="test-snap.snap", content="dummy snap content")
        self.factory.makeSnapFile(snapbuild=snapbuild, libraryfile=snap_lfa)
        manifest_lfa = self.factory.makeLibraryFileAlias(
            filename="test-snap.manifest", content="dummy manifest content")
        self.factory.makeSnapFile(
            snapbuild=snapbuild, libraryfile=manifest_lfa)
        return snapbuild

    def test_upload(self):
        snapbuild = self.makeUploadableSnapBuild()
        transaction.commit()
        with dbuser(config.ISnapStoreUploadJobSource.dbuser):
            with HTTMock(self._unscanned_upload_handler,
                         self._snap_push_handler):
                self.assertEqual(
                    "http://sca.example/dev/api/snaps/1/builds/1/status",
                    self.client.upload(snapbuild))
        self.assertThat(self.unscanned_upload_requests, MatchesListwise([
            RequestMatches(
                url=Equals("http://updown.example/unscanned-upload/"),
                method=Equals("POST"),
                form_data={
                    "binary": MatchesStructure.byEquality(
                        name="binary", filename="test-snap.snap",
                        value="dummy snap content",
                        type="application/octet-stream",
                        )})]))
        self.assertThat(self.snap_push_request, RequestMatches(
            url=Equals("http://sca.example/dev/api/snap-push/"),
            method=Equals("POST"),
            headers=ContainsDict({"Content-Type": Equals("application/json")}),
            auth=("Macaroon", MacaroonsVerify(self.root_key)),
            json_data={
                "name": "test-snap", "updown_id": 1, "series": "rolling",
                }))

    def test_upload_no_discharge(self):
        root_key = hashlib.sha256(self.factory.getUniqueString()).hexdigest()
        root_macaroon = Macaroon(key=root_key)
        snapbuild = self.makeUploadableSnapBuild(
            store_secrets={"root": root_macaroon.serialize()})
        transaction.commit()
        with dbuser(config.ISnapStoreUploadJobSource.dbuser):
            with HTTMock(self._unscanned_upload_handler,
                         self._snap_push_handler):
                self.assertEqual(
                    "http://sca.example/dev/api/snaps/1/builds/1/status",
                    self.client.upload(snapbuild))
        self.assertThat(self.unscanned_upload_requests, MatchesListwise([
            RequestMatches(
                url=Equals("http://updown.example/unscanned-upload/"),
                method=Equals("POST"),
                form_data={
                    "binary": MatchesStructure.byEquality(
                        name="binary", filename="test-snap.snap",
                        value="dummy snap content",
                        type="application/octet-stream",
                        )})]))
        self.assertThat(self.snap_push_request, RequestMatches(
            url=Equals("http://sca.example/dev/api/snap-push/"),
            method=Equals("POST"),
            headers=ContainsDict({"Content-Type": Equals("application/json")}),
            auth=("Macaroon", MacaroonsVerify(root_key)),
            json_data={
                "name": "test-snap", "updown_id": 1, "series": "rolling",
                }))

    def test_upload_unauthorized(self):
        @urlmatch(path=r".*/snap-push/$")
        def snap_push_handler(url, request):
            self.snap_push_request = request
            return {
                "status_code": 401,
                "headers": {"WWW-Authenticate": 'Macaroon realm="Devportal"'},
                "content": {
                    "error_list": [{
                        "code": "macaroon-permission-required",
                        "message": "Permission is required: package_push",
                        }],
                    },
                }

        store_secrets = self._make_store_secrets()
        snapbuild = self.makeUploadableSnapBuild(store_secrets=store_secrets)
        transaction.commit()
        with dbuser(config.ISnapStoreUploadJobSource.dbuser):
            with HTTMock(self._unscanned_upload_handler, snap_push_handler,
                         self._macaroon_refresh_handler):
                self.assertRaisesWithContent(
                    UnauthorizedUploadResponse,
                    "Permission is required: package_push",
                    self.client.upload, snapbuild)

    def test_upload_needs_discharge_macaroon_refresh(self):
        @urlmatch(path=r".*/snap-push/$")
        def snap_push_handler(url, request):
            snap_push_handler.call_count += 1
            if snap_push_handler.call_count == 1:
                self.first_snap_push_request = request
                return {
                    "status_code": 401,
                    "headers": {
                        "WWW-Authenticate": "Macaroon needs_refresh=1"}}
            else:
                return self._snap_push_handler(url, request)
        snap_push_handler.call_count = 0

        store_secrets = self._make_store_secrets()
        snapbuild = self.makeUploadableSnapBuild(store_secrets=store_secrets)
        transaction.commit()
        with dbuser(config.ISnapStoreUploadJobSource.dbuser):
            with HTTMock(self._unscanned_upload_handler, snap_push_handler,
                         self._macaroon_refresh_handler):
                self.assertEqual(
                    "http://sca.example/dev/api/snaps/1/builds/1/status",
                    self.client.upload(snapbuild))
        self.assertEqual(2, snap_push_handler.call_count)
        self.assertNotEqual(
            store_secrets["discharge"],
            snapbuild.snap.store_secrets["discharge"])

    def test_upload_unsigned_agreement(self):
        @urlmatch(path=r".*/snap-push/$")
        def snap_push_handler(url, request):
            self.snap_push_request = request
            return {
                "status_code": 403,
                "content": {
                    "error_list": [
                        {"message": "Developer has not signed agreement."},
                        ],
                    },
                }

        store_secrets = self._make_store_secrets()
        snapbuild = self.makeUploadableSnapBuild(store_secrets=store_secrets)
        transaction.commit()
        with dbuser(config.ISnapStoreUploadJobSource.dbuser):
            with HTTMock(self._unscanned_upload_handler, snap_push_handler,
                         self._macaroon_refresh_handler):
                err = self.assertRaises(
                    UploadFailedResponse, self.client.upload, snapbuild)
                self.assertEqual(
                    "Developer has not signed agreement.", str(err))
                self.assertFalse(err.can_retry)

    def test_upload_file_error(self):
        @urlmatch(path=r".*/unscanned-upload/$")
        def unscanned_upload_handler(url, request):
            return {
                "status_code": 502,
                "reason": "Proxy Error",
                "content": b"The proxy exploded.\n",
                }

        store_secrets = self._make_store_secrets()
        snapbuild = self.makeUploadableSnapBuild(store_secrets=store_secrets)
        transaction.commit()
        with dbuser(config.ISnapStoreUploadJobSource.dbuser):
            with HTTMock(unscanned_upload_handler):
                err = self.assertRaises(
                    UploadFailedResponse, self.client.upload, snapbuild)
                self.assertEqual("502 Server Error: Proxy Error", str(err))
                self.assertEqual(b"The proxy exploded.\n", err.detail)
                self.assertTrue(err.can_retry)

    def test_refresh_discharge_macaroon(self):
        store_secrets = self._make_store_secrets()
        snap = self.factory.makeSnap(
            store_upload=True,
            store_series=self.factory.makeSnappySeries(name="rolling"),
            store_name="test-snap", store_secrets=store_secrets)

        with dbuser(config.ISnapStoreUploadJobSource.dbuser):
            with HTTMock(self._macaroon_refresh_handler):
                self.client.refreshDischargeMacaroon(snap)
        self.assertThat(self.refresh_request, RequestMatches(
            url=Equals("http://sso.example/api/v2/tokens/refresh"),
            method=Equals("POST"),
            headers=ContainsDict({"Content-Type": Equals("application/json")}),
            json_data={"discharge_macaroon": store_secrets["discharge"]}))
        self.assertNotEqual(
            store_secrets["discharge"], snap.store_secrets["discharge"])

    def test_checkStatus_pending(self):
        @all_requests
        def handler(url, request):
            return {
                "status_code": 200,
                "content": {
                    "code": "being_processed", "processed": False,
                    "can_release": False,
                    }}

        status_url = "http://sca.example/dev/api/snaps/1/builds/1/status"
        with HTTMock(handler):
            self.assertRaises(
                UploadNotScannedYetResponse, self.client.checkStatus,
                status_url)

    def test_checkStatus_error(self):
        @all_requests
        def handler(url, request):
            return {
                "status_code": 200,
                "content": {
                    "code": "processing_error", "processed": True,
                    "can_release": False,
                    "errors": [
                        {"code": None,
                         "message": "You cannot use that reserved namespace.",
                         "link": "http://example.com"
                         }],
                    }}

        status_url = "http://sca.example/dev/api/snaps/1/builds/1/status"
        with HTTMock(handler):
            self.assertRaisesWithContent(
                ScanFailedResponse,
                b"You cannot use that reserved namespace.",
                self.client.checkStatus, status_url)

    def test_checkStatus_review_error(self):
        @all_requests
        def handler(url, request):
            return {
                "status_code": 200,
                "content": {
                    "code": "processing_error", "processed": True,
                    "can_release": False,
                    "errors": [{"code": None, "message": "Review failed."}],
                    "url": "http://sca.example/dev/click-apps/1/rev/1/",
                    }}

        status_url = "http://sca.example/dev/api/snaps/1/builds/1/status"
        with HTTMock(handler):
            self.assertRaisesWithContent(
                ScanFailedResponse, b"Review failed.",
                self.client.checkStatus, status_url)

    def test_checkStatus_complete(self):
        @all_requests
        def handler(url, request):
            return {
                "status_code": 200,
                "content": {
                    "code": "ready_to_release", "processed": True,
                    "can_release": True,
                    "url": "http://sca.example/dev/click-apps/1/rev/1/",
                    "revision": 1,
                    }}

        status_url = "http://sca.example/dev/api/snaps/1/builds/1/status"
        with HTTMock(handler):
            self.assertEqual(
                ("http://sca.example/dev/click-apps/1/rev/1/", 1),
                self.client.checkStatus(status_url))

    def test_checkStatus_404(self):
        @all_requests
        def handler(url, request):
            return {"status_code": 404, "reason": b"Not found"}

        status_url = "http://sca.example/dev/api/snaps/1/builds/1/status"
        with HTTMock(handler):
            self.assertRaisesWithContent(
                BadScanStatusResponse, b"404 Client Error: Not found",
                self.client.checkStatus, status_url)

    def test_listChannels(self):
        memcache_key = "search.example:channels".encode("UTF-8")
        try:
            with HTTMock(self._channels_handler):
                self.assertEqual(self.channels, self.client.listChannels())
            self.assertThat(self.channels_request, RequestMatches(
                url=Equals("http://search.example/api/v1/channels"),
                method=Equals("GET"),
                headers=ContainsDict(
                    {"Accept": Equals("application/hal+json")})))
            self.assertEqual(
                self.channels,
                json.loads(getUtility(IMemcacheClient).get(memcache_key)))
            self.channels_request = None
            with HTTMock(self._channels_handler):
                self.assertEqual(self.channels, self.client.listChannels())
            self.assertIsNone(self.channels_request)
        finally:
            getUtility(IMemcacheClient).delete(memcache_key)

    def test_listChannels_404(self):
        @all_requests
        def handler(url, request):
            return {"status_code": 404, "reason": b"Not found"}

        with HTTMock(handler):
            self.assertRaisesWithContent(
                BadSearchResponse, b"404 Client Error: Not found",
                self.client.listChannels)

    def test_listChannels_disable_search(self):
        @all_requests
        def handler(url, request):
            self.request = request
            return {"status_code": 404, "reason": b"Not found"}

        self.useFixture(
            FeatureFixture({u"snap.disable_channel_search": u"on"}))
        expected_channels = [
            {"name": "candidate", "display_name": "Candidate"},
            {"name": "edge", "display_name": "Edge"},
            {"name": "beta", "display_name": "Beta"},
            {"name": "stable", "display_name": "Stable"},
            ]
        self.request = None
        with HTTMock(handler):
            self.assertEqual(expected_channels, self.client.listChannels())
        self.assertIsNone(self.request)
        memcache_key = "search.example:channels".encode("UTF-8")
        self.assertIsNone(getUtility(IMemcacheClient).get(memcache_key))

    def test_release(self):
        with HTTMock(self._channels_handler):
            snap = self.factory.makeSnap(
                store_upload=True,
                store_series=self.factory.makeSnappySeries(name="rolling"),
                store_name="test-snap",
                store_secrets=self._make_store_secrets(),
                store_channels=["stable", "edge"])
        snapbuild = self.factory.makeSnapBuild(snap=snap)
        with HTTMock(self._snap_release_handler):
            self.client.release(snapbuild, 1)
        self.assertThat(self.snap_release_request, RequestMatches(
            url=Equals("http://sca.example/dev/api/snap-release/"),
            method=Equals("POST"),
            headers=ContainsDict({"Content-Type": Equals("application/json")}),
            auth=("Macaroon", MacaroonsVerify(self.root_key)),
            json_data={
                "name": "test-snap", "revision": 1,
                "channels": ["stable", "edge"], "series": "rolling",
                }))

    def test_release_no_discharge(self):
        root_key = hashlib.sha256(self.factory.getUniqueString()).hexdigest()
        root_macaroon = Macaroon(key=root_key)
        with HTTMock(self._channels_handler):
            snap = self.factory.makeSnap(
                store_upload=True,
                store_series=self.factory.makeSnappySeries(name="rolling"),
                store_name="test-snap",
                store_secrets={"root": root_macaroon.serialize()},
                store_channels=["stable", "edge"])
        snapbuild = self.factory.makeSnapBuild(snap=snap)
        with HTTMock(self._snap_release_handler):
            self.client.release(snapbuild, 1)
        self.assertThat(self.snap_release_request, RequestMatches(
            url=Equals("http://sca.example/dev/api/snap-release/"),
            method=Equals("POST"),
            headers=ContainsDict({"Content-Type": Equals("application/json")}),
            auth=("Macaroon", MacaroonsVerify(root_key)),
            json_data={
                "name": "test-snap", "revision": 1,
                "channels": ["stable", "edge"], "series": "rolling",
                }))

    def test_release_needs_discharge_macaroon_refresh(self):
        @urlmatch(path=r".*/snap-release/$")
        def snap_release_handler(url, request):
            snap_release_handler.call_count += 1
            if snap_release_handler.call_count == 1:
                self.first_snap_release_request = request
                return {
                    "status_code": 401,
                    "headers": {
                        "WWW-Authenticate": "Macaroon needs_refresh=1"}}
            else:
                return self._snap_release_handler(url, request)
        snap_release_handler.call_count = 0

        store_secrets = self._make_store_secrets()
        with HTTMock(self._channels_handler):
            snap = self.factory.makeSnap(
                store_upload=True,
                store_series=self.factory.makeSnappySeries(name="rolling"),
                store_name="test-snap", store_secrets=store_secrets,
                store_channels=["stable", "edge"])
        snapbuild = self.factory.makeSnapBuild(snap=snap)
        with HTTMock(snap_release_handler, self._macaroon_refresh_handler):
            self.client.release(snapbuild, 1)
        self.assertEqual(2, snap_release_handler.call_count)
        self.assertNotEqual(
            store_secrets["discharge"], snap.store_secrets["discharge"])

    def test_release_error(self):
        @urlmatch(path=r".*/snap-release/$")
        def handler(url, request):
            return {
                "status_code": 503,
                "content": {"error_list": [{"message": "Failed to publish"}]},
                }

        with HTTMock(self._channels_handler):
            snap = self.factory.makeSnap(
                store_upload=True,
                store_series=self.factory.makeSnappySeries(name="rolling"),
                store_name="test-snap",
                store_secrets=self._make_store_secrets(),
                store_channels=["stable", "edge"])
        snapbuild = self.factory.makeSnapBuild(snap=snap)
        with HTTMock(handler):
            self.assertRaisesWithContent(
                ReleaseFailedResponse, "Failed to publish",
                self.client.release, snapbuild, 1)

    def test_release_404(self):
        @urlmatch(path=r".*/snap-release/$")
        def handler(url, request):
            return {"status_code": 404, "reason": b"Not found"}

        with HTTMock(self._channels_handler):
            snap = self.factory.makeSnap(
                store_upload=True,
                store_series=self.factory.makeSnappySeries(name="rolling"),
                store_name="test-snap",
                store_secrets=self._make_store_secrets(),
                store_channels=["stable", "edge"])
        snapbuild = self.factory.makeSnapBuild(snap=snap)
        with HTTMock(handler):
            self.assertRaisesWithContent(
                ReleaseFailedResponse, b"404 Client Error: Not found",
                self.client.release, snapbuild, 1)
