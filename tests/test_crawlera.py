from unittest import TestCase

from w3lib.http import basic_auth_header
from scrapy.http import Request, Response
from scrapy.spider import Spider
from scrapy.utils.test import get_crawler
from twisted.internet.error import ConnectionRefusedError

from scrapylib.crawlera import CrawleraMiddleware
import os


class MockedSlot(object):

    def __init__(self, delay=0.0):
        self.delay = delay


class CrawleraMiddlewareTestCase(TestCase):

    mwcls = CrawleraMiddleware
    bancode = 503

    def setUp(self):
        self.spider = Spider('foo')
        self.settings = {'CRAWLERA_USER': 'user', 'CRAWLERA_PASS': 'pass'}

    def _mock_crawler(self, settings=None):

        class MockedDownloader(object):
            slots = {}

        class MockedEngine(object):
            downloader = MockedDownloader()
            fake_spider_closed_result = None

            def close_spider(self, spider, reason):
                self.fake_spider_closed_result = (spider, reason)

        crawler = get_crawler(settings)
        crawler.engine = MockedEngine()
        return crawler

    def _assert_disabled(self, spider, settings=None):
        crawler = self._mock_crawler(settings)
        mw = self.mwcls.from_crawler(crawler)
        mw.open_spider(spider)
        req = Request('http://www.scrapytest.org')
        out = mw.process_request(req, spider)
        self.assertEqual(out, None)
        self.assertEqual(req.meta.get('proxy'), None)
        self.assertEqual(req.meta.get('download_timeout'), None)
        self.assertEqual(req.headers.get('Proxy-Authorization'), None)
        res = Response(req.url)
        assert mw.process_response(req, res, spider) is res
        res = Response(req.url, status=mw.ban_code)
        assert mw.process_response(req, res, spider) is res

    def _assert_enabled(self, spider,
                        settings=None,
                        proxyurl='http://proxy.crawlera.com:8010?noconnect',
                        proxyauth=basic_auth_header('user', 'pass'),
                        maxbans=400,
                        download_timeout=1800):
        crawler = self._mock_crawler(settings)
        mw = self.mwcls.from_crawler(crawler)
        mw.open_spider(spider)
        req = Request('http://www.scrapytest.org')
        assert mw.process_request(req, spider) is None
        self.assertEqual(req.meta.get('proxy'), proxyurl)
        self.assertEqual(req.meta.get('download_timeout'), download_timeout)
        self.assertEqual(req.headers.get('Proxy-Authorization'), proxyauth)
        res = Response(req.url)
        assert mw.process_response(req, res, spider) is res

        # disabled if 'dont_proxy' is set
        req = Request('http://www.scrapytest.org')
        req.meta['dont_proxy'] = True
        assert mw.process_request(req, spider) is None
        self.assertEqual(req.meta.get('proxy'), None)
        self.assertEqual(req.meta.get('download_timeout'), None)
        self.assertEqual(req.headers.get('Proxy-Authorization'), None)
        res = Response(req.url)
        assert mw.process_response(req, res, spider) is res
        del req.meta['dont_proxy']

        if maxbans > 0:
            # assert ban count is reseted after a succesful response
            res = Response('http://ban.me', status=self.bancode)
            assert mw.process_response(req, res, spider) is res
            self.assertEqual(crawler.engine.fake_spider_closed_result, None)
            res = Response('http://unban.me')
            assert mw.process_response(req, res, spider) is res
            self.assertEqual(crawler.engine.fake_spider_closed_result, None)
            self.assertEqual(mw._bans[None], 0)

        # check for not banning before maxbans for bancode
        for x in xrange(maxbans + 1):
            self.assertEqual(crawler.engine.fake_spider_closed_result, None)
            res = Response('http://ban.me/%d' % x, status=self.bancode)
            assert mw.process_response(req, res, spider) is res

        # max bans reached and close_spider called
        self.assertEqual(crawler.engine.fake_spider_closed_result, (spider, 'banned'))

    def test_disabled_by_lack_of_crawlera_settings(self):
        self._assert_disabled(self.spider, settings={})

    def test_spider_crawlera_enabled(self):
        self.assertFalse(hasattr(self.spider, 'crawlera_enabled'))
        self._assert_disabled(self.spider, self.settings)
        self.spider.crawlera_enabled = True
        self._assert_enabled(self.spider, self.settings)
        self.spider.crawlera_enabled = False
        self._assert_disabled(self.spider, self.settings)

    def test_enabled(self):
        self._assert_disabled(self.spider, self.settings)
        self.settings['CRAWLERA_ENABLED'] = True
        self._assert_enabled(self.spider, self.settings)

    def test_userpass(self):
        self.spider.crawlera_enabled = True
        self.settings['CRAWLERA_USER'] = user = 'other'
        self.settings['CRAWLERA_PASS'] = pass_ = 'secret'
        proxyauth = basic_auth_header(user, pass_)
        self._assert_enabled(self.spider, self.settings, proxyauth=proxyauth)

        self.spider.crawlera_user = user = 'notfromsettings'
        self.spider.crawlera_pass = pass_ = 'anothersecret'
        proxyauth = basic_auth_header(user, pass_)
        self._assert_enabled(self.spider, self.settings, proxyauth=proxyauth)

    def test_proxyurl(self):
        self.spider.crawlera_enabled = True
        self.settings['CRAWLERA_URL'] = 'http://localhost:8010'
        self._assert_enabled(self.spider, self.settings, proxyurl='http://localhost:8010?noconnect')

    def test_proxyurl_including_noconnect(self):
        self.spider.crawlera_enabled = True
        self.settings['CRAWLERA_URL'] = 'http://localhost:8010?noconnect'
        self._assert_enabled(self.spider, self.settings, proxyurl='http://localhost:8010?noconnect')

    def test_maxbans(self):
        self.spider.crawlera_enabled = True
        self.settings['CRAWLERA_MAXBANS'] = maxbans = 0
        self._assert_enabled(self.spider, self.settings, maxbans=maxbans)
        self.settings['CRAWLERA_MAXBANS'] = maxbans = 100
        self._assert_enabled(self.spider, self.settings, maxbans=maxbans)
        # Assert setting is coerced into correct type
        self.settings['CRAWLERA_MAXBANS'] = '123'
        self._assert_enabled(self.spider, self.settings, maxbans=123)
        self.spider.crawlera_maxbans = 99
        self._assert_enabled(self.spider, self.settings, maxbans=99)

    def test_download_timeout(self):
        self.spider.crawlera_enabled = True
        self.settings['CRAWLERA_DOWNLOAD_TIMEOUT'] = 60
        self._assert_enabled(self.spider, self.settings, download_timeout=60)
        # Assert setting is coerced into correct type
        self.settings['CRAWLERA_DOWNLOAD_TIMEOUT'] = '42'
        self._assert_enabled(self.spider, self.settings, download_timeout=42)
        self.spider.crawlera_download_timeout = 120
        self._assert_enabled(self.spider, self.settings, download_timeout=120)

    def test_hooks(self):
        class _ECLS(self.mwcls):
            def is_enabled(self, spider):
                wascalled.append('is_enabled')
                return enabled

            def get_proxyauth(self, spider):
                wascalled.append('get_proxyauth')
                return proxyauth

        wascalled = []
        self.mwcls = _ECLS

        # test is_enabled returns False
        enabled = False
        self.spider.crawlera_enabled = True
        self._assert_disabled(self.spider, self.settings)
        self.assertEqual(wascalled, ['is_enabled'])

        wascalled[:] = []  # reset
        enabled = True
        self.spider.crawlera_enabled = False
        proxyauth = 'Basic Foo'
        self._assert_enabled(self.spider, self.settings, proxyauth=proxyauth)
        self.assertEqual(wascalled, ['is_enabled', 'get_proxyauth'])

    def test_delay_adjustment(self):
        delay = 0.5
        slot_key = 'www.scrapytest.org'
        url = 'http://www.scrapytest.org'
        ban_url = 'http://ban.me'

        self.spider.crawlera_enabled = True

        crawler = self._mock_crawler(self.settings)
        # ignore spider delay by default
        self.spider.download_delay = delay
        mw = self.mwcls.from_crawler(crawler)
        mw.open_spider(self.spider)
        self.assertEqual(self.spider.download_delay, 0)

        # preserve original delay
        self.spider.download_delay = delay
        self.spider.crawlera_preserve_delay = True
        mw = self.mwcls.from_crawler(crawler)
        mw.open_spider(self.spider)
        self.assertEqual(self.spider.download_delay, delay)

        slot = MockedSlot(self.spider.download_delay)
        crawler.engine.downloader.slots[slot_key] = slot

        # ban
        req = Request(url, meta={'download_slot': slot_key})
        res = Response(ban_url, status=self.bancode, request=req)
        mw.process_response(req, res, self.spider)
        self.assertEqual(slot.delay, delay)
        self.assertEqual(self.spider.download_delay, delay)

        retry_after = 1.5
        headers = {'retry-after': str(retry_after)}
        res = Response(
            ban_url, status=self.bancode, headers=headers, request=req)
        mw.process_response(req, res, self.spider)
        self.assertEqual(slot.delay, retry_after)
        self.assertEqual(self.spider.download_delay, delay)

        res = Response(url, request=req)
        mw.process_response(req, res, self.spider)
        self.assertEqual(slot.delay, delay)
        self.assertEqual(self.spider.download_delay, delay)

        # server failures
        mw.process_exception(req, ConnectionRefusedError(), self.spider)
        self.assertEqual(slot.delay, mw.connection_refused_delay)
        self.assertEqual(self.spider.download_delay, delay)

        res = Response(ban_url, request=req)
        mw.process_response(req, res, self.spider)
        self.assertEqual(slot.delay, delay)
        self.assertEqual(self.spider.download_delay, delay)

        mw.process_exception(req, ConnectionRefusedError(), self.spider)
        self.assertEqual(slot.delay, mw.connection_refused_delay)
        self.assertEqual(self.spider.download_delay, delay)

        res = Response(ban_url, status=self.bancode, request=req)
        mw.process_response(req, res, self.spider)
        self.assertEqual(slot.delay, delay)
        self.assertEqual(self.spider.download_delay, delay)

    def test_jobid_header(self):
        # test without the environment variable 'SCRAPY_JOB'
        self.spider.crawlera_enabled = True
        crawler = self._mock_crawler(self.settings)
        mw = self.mwcls.from_crawler(crawler)
        mw.open_spider(self.spider)
        req = Request('http://www.scrapytest.org')
        self.assertEqual(mw.process_request(req, self.spider), None)
        self.assertEqual(req.headers.get('X-Crawlera-Jobid'), None)

        # test with the environment variable 'SCRAPY_JOB'
        os.environ['SCRAPY_JOB'] = '2816'
        self.spider.crawlera_enabled = True
        crawler1 = self._mock_crawler(self.settings)
        mw1 = self.mwcls.from_crawler(crawler)
        mw1.open_spider(self.spider)
        req1 = Request('http://www.scrapytest.org')
        self.assertEqual(mw1.process_request(req1, self.spider), None)
        self.assertEqual(req1.headers.get('X-Crawlera-Jobid'), '2816')

    def test_https_header(self):
        # without https enabled
        self.spider.crawlera_enabled = True
        crawler = self._mock_crawler(self.settings)
        mw = self.mwcls.from_crawler(crawler)
        mw.open_spider(self.spider)
        req = Request('https://www.scrapytest.org/')
        self.assertEqual(mw.process_request(req, self.spider), None)
        self.assertNotEqual(req.headers.get('X-Crawlera-Use-HTTPS'), '1')

        # with https enabled
        self.spider.crawlera_https = True
        crawler1 = self._mock_crawler(self.settings)
        mw1 = self.mwcls.from_crawler(crawler)
        mw1.open_spider(self.spider)
        req1 = Request('https://www.scrapytest.org/')
        self.assertEqual(mw1.process_request(req1, self.spider), None)
        self.assertEqual(req1.headers.get('X-Crawlera-Use-HTTPS'), '1')
