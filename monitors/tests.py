import io
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests
from django.contrib import admin
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from monitors.models import AgencyCheck, AgencyMonitor, MonitorRun
from monitors.services.bid_detector import find_entries
from monitors.services.container import find_container
from monitors.services.fetcher import FetchResult, MAX_REDIRECTS, USER_AGENT, fetch_page
from monitors.services.monitor import CheckResult, check_agency, save_check_result


class FindContainerTests(SimpleTestCase):
	def test_css_selector_returns_first_matching_element(self):
		element, reason = find_container(
			'<html><body><table id="first" class="rpfbids"></table>'
			'<table id="second" class="rpfbids"></table></body></html>',
			'table.rpfbids',
		)

		self.assertEqual(element.tag, 'table')
		self.assertEqual(element.get('id'), 'first')
		self.assertIsNone(reason)

	def test_xpath_selector_returns_first_matching_element(self):
		element, reason = find_container(
			'<html><body><table class="rpfbids"></table></body></html>',
			'//table[@class="rpfbids"]',
		)

		self.assertEqual(element.tag, 'table')
		self.assertIsNone(reason)

	def test_missing_selector_returns_reason(self):
		element, reason = find_container('<html></html>', '')

		self.assertIsNone(element)
		self.assertEqual(reason, 'missing_selector')

	def test_no_match_returns_reason(self):
		element, reason = find_container('<html></html>', 'table.rpfbids')

		self.assertIsNone(element)
		self.assertEqual(reason, 'container_not_found')

	def test_invalid_css_selector_returns_reason(self):
		element, reason = find_container('<html></html>', 'table[')

		self.assertIsNone(element)
		self.assertTrue(reason.startswith('invalid_css_selector:'))

	def test_invalid_xpath_selector_returns_reason(self):
		element, reason = find_container('<html></html>', '//*[ ')

		self.assertIsNone(element)
		self.assertTrue(reason.startswith('invalid_xpath_selector:'))


class FindEntriesTests(SimpleTestCase):
	def test_custom_selector_returns_matching_entries(self):
		container, _reason = find_container(
			'<div><article class="bid">First</article>'
			'<article class="bid">Second</article></div>',
			'div',
		)

		entries = find_entries(container, 'article.bid')

		self.assertEqual([entry.text_content() for entry in entries], ['First', 'Second'])

	def test_table_default_skips_header_and_empty_rows(self):
		container, _reason = find_container(
			'<table><tbody><tr><th>Bid</th></tr><tr></tr>'
			'<tr><td>First bid</td></tr><tr><td>Second bid</td></tr>'
			'</tbody></table>',
			'table',
		)

		entries = find_entries(container, None)

		self.assertEqual(
			[entry.text_content().strip() for entry in entries],
			['First bid', 'Second bid'],
		)

	def test_list_default_returns_nonempty_items(self):
		container, _reason = find_container(
			'<ul><li>First bid</li><li></li><li>Second bid</li></ul>',
			'ul',
		)

		entries = find_entries(container, '')

		self.assertEqual([entry.text_content() for entry in entries], ['First bid', 'Second bid'])

	def test_card_default_uses_direct_children_and_skips_headers(self):
		container, _reason = find_container(
			'<div><div class="bidsHeader listHeader">Bids</div>'
			'<div class="listItemsRow bid">First bid</div>'
			'<div class="listItemsRow bid alt">Second bid</div></div>',
			'div',
		)

		entries = find_entries(container, None)

		self.assertEqual(
			[entry.text_content() for entry in entries],
			['First bid', 'Second bid'],
		)


class CheckAgencyTests(SimpleTestCase):
	def make_agency(self, **overrides):
		values = {
			'agency_url': 'https://agency.example/bids',
			'fetch_mode': 'http',
			'container_selector': '.bids',
			'bid_selector': '.bid',
			'due_date_selector': '.closes',
			'date_format': '%m/%d/%Y',
			'timezone': 'America/New_York',
			'no_bid_phrase': 'No current bids',
		}
		values.update(overrides)
		return Mock(**values)

	def check_html(self, html, **agency_overrides):
		with patch(
			'monitors.services.monitor.fetch_page',
			return_value=FetchResult(html, 200, None),
		):
			return check_agency(self.make_agency(**agency_overrides))

	def test_open_bid_status_is_active_without_considering_due_date(self):
		result = self.check_html(
			'<div class="bids"><div class="bid"><div class="bidStatus">'
			'<div><span>Status:</span><br><span>Closes:</span></div>'
			'<div><span>Open</span><br><span>01/01/2000 1:00 PM</span></div>'
			'</div></div></div>'
		)

		self.assertEqual(result.status, 'ACTIVE')
		self.assertEqual(result.reason, 'open_bid_found')
		self.assertEqual(result.entries_found, 1)
		self.assertEqual(result.dates_parsed, 0)

	def test_closed_bid_status_is_no_bid(self):
		result = self.check_html(
			'<div class="bids"><div class="bid"><div class="bidStatus">'
			'<div><span>Status:</span><br><span>Closes:</span></div>'
			'<div><span>Closed</span><br><span>12/31/2099</span></div>'
			'</div></div></div>'
		)

		self.assertEqual(result.status, 'NO_BID')
		self.assertEqual(result.reason, 'no_open_bids')

	def test_date_without_status_is_unknown(self):
		result = self.check_html(
			'<div class="bids"><div class="bid"><span class="closes">'
			'12/31/2099</span></div></div>'
		)

		self.assertEqual(result.status, 'UNKNOWN')
		self.assertEqual(result.reason, 'status_not_found')

	def test_missing_container_is_unknown_even_when_phrase_is_configured(self):
		result = self.check_html('<div>Nothing here</div>')

		self.assertEqual(result.status, 'UNKNOWN')
		self.assertEqual(result.reason, 'container_missing')

	def test_empty_container_with_no_bid_phrase_is_no_bid(self):
		result = self.check_html('<div class="bids">No current bids at this time</div>')

		self.assertEqual(result.status, 'NO_BID')
		self.assertEqual(result.reason, 'no_bids_phrase')

	def test_empty_container_without_no_bid_phrase_is_unknown(self):
		result = self.check_html('<div class="bids">Welcome</div>')

		self.assertEqual(result.status, 'UNKNOWN')
		self.assertEqual(result.reason, 'no_entries')

	def test_fetch_failure_is_error(self):
		with patch(
			'monitors.services.monitor.fetch_page',
			return_value=FetchResult(None, None, 'timeout'),
		):
			result = check_agency(self.make_agency())

		self.assertEqual(result.status, 'ERROR')
		self.assertEqual(result.reason, 'fetch_failed')
		self.assertEqual(result.error, 'timeout')

	def test_broken_container_selector_is_unknown(self):
		result = self.check_html(
			'<div class="bids">No current bids</div>',
			container_selector='div[',
		)

		self.assertEqual(result.status, 'UNKNOWN')
		self.assertEqual(result.reason, 'container_missing')

	def test_invalid_entry_selector_is_error_and_does_not_raise(self):
		result = self.check_html(
			'<div class="bids"><div class="bid">Bid</div></div>',
			bid_selector='div[',
		)

		self.assertEqual(result.status, 'ERROR')
		self.assertEqual(result.reason, 'processing_error')
		self.assertTrue(result.error)


class SaveCheckResultTests(TestCase):
	def setUp(self):
		self.agency = AgencyMonitor.objects.create(
			agency_name='Test Agency',
			ecgains='test-agency',
			agency_url='https://agency.example/bids',
			container_selector='.bids',
			broken=True,
		)
		self.run = MonitorRun.objects.create(
			run_date='2026-10-02',
			started_at='2026-10-02T09:00:00Z',
		)

	def test_saves_check_and_updates_agency_status(self):
		result = CheckResult(
			status='ACTIVE',
			reason='open_bid_found',
			container_found=True,
			entries_found=3,
			dates_parsed=0,
			error='',
			duration_ms=42,
		)

		check = save_check_result(self.run, self.agency, result)

		self.assertIsInstance(check, AgencyCheck)
		self.assertEqual(check.run, self.run)
		self.assertEqual(check.agency, self.agency)
		self.assertEqual(check.status, 'ACTIVE')
		self.assertTrue(check.broken_at_check)
		self.assertTrue(check.container_found)
		self.assertEqual(check.entries_found, 3)
		self.assertEqual(check.dates_parsed, 0)
		self.assertEqual(check.reason, 'open_bid_found')
		self.assertEqual(check.error, '')
		self.assertEqual(check.duration_ms, 42)
		self.assertIsNotNone(check.checked_at)

		self.agency.refresh_from_db()
		self.assertEqual(self.agency.last_status, 'ACTIVE')
		self.assertIsNotNone(self.agency.last_checked_at)
		self.assertEqual(self.agency.last_error, '')

	def test_failure_error_is_copied_to_check_and_agency(self):
		result = CheckResult(
			status='ERROR',
			reason='fetch_failed',
			error='timeout',
			duration_ms=120,
		)

		check = save_check_result(self.run, self.agency, result)

		self.assertEqual(check.error, 'timeout')
		self.assertEqual(check.status, 'ERROR')
		self.agency.refresh_from_db()
		self.assertEqual(self.agency.last_status, 'ERROR')
		self.assertEqual(self.agency.last_error, 'timeout')

	def test_saving_same_agency_twice_updates_run_check(self):
		first = CheckResult(
			status='ACTIVE',
			reason='open_bid_found',
			container_found=True,
			entries_found=3,
		)
		second = CheckResult(
			status='NO_BID',
			reason='no_bids_phrase',
			container_found=True,
		)

		first_check = save_check_result(self.run, self.agency, first)
		second_check = save_check_result(self.run, self.agency, second)

		self.assertEqual(first_check.pk, second_check.pk)
		self.assertEqual(AgencyCheck.objects.filter(run=self.run, agency=self.agency).count(), 1)
		second_check.refresh_from_db()
		self.assertEqual(second_check.status, 'NO_BID')
		self.assertEqual(second_check.reason, 'no_bids_phrase')

	def test_check_result_is_saved_for_admin_review(self):
		with patch(
			'monitors.services.monitor.fetch_page',
			return_value=FetchResult(
				'<div class="bids"><div class="bid"><span>Open</span></div></div>',
				200,
				None,
			),
		):
			result = check_agency(self.agency)

		check = save_check_result(self.run, self.agency, result)
		saved_check = AgencyCheck.objects.get(pk=check.pk)

		self.assertEqual(saved_check.status, 'ACTIVE')
		self.assertEqual(saved_check.reason, 'open_bid_found')
		self.assertEqual(saved_check.entries_found, 1)
		self.assertEqual(saved_check.duration_ms, result.duration_ms)
		self.assertTrue(admin.site.is_registered(AgencyCheck))

		self.agency.refresh_from_db()
		self.assertEqual(self.agency.last_status, 'ACTIVE')
		self.assertIsNotNone(self.agency.last_checked_at)


class CheckAgenciesCommandTests(TestCase):
	@patch(
		'monitors.management.commands.check_agencies.load_site_urls',
		return_value=[
			'https://active.example/Bids.aspx',
			'https://unknown.example/Bids.aspx',
			'https://error.example/Bids.aspx',
		],
	)
	@patch('monitors.management.commands.check_agencies.check_agency')
	def test_command_saves_results_continues_after_failure_and_counts_statuses(
		self,
		check_agency_mock,
		_load_urls,
	):
		check_agency_mock.side_effect = [
			CheckResult('ACTIVE', 'open_bid_found', True, 2),
			CheckResult('UNKNOWN', 'container_missing'),
			RuntimeError('unexpected agency failure'),
		]

		call_command('check_agencies', verbosity=0)

		run = MonitorRun.objects.get()
		self.assertEqual(run.total_agencies, 3)
		self.assertEqual(run.active_agencies, 1)
		self.assertEqual(run.no_bid_agencies, 0)
		self.assertEqual(run.unknown_agencies, 1)
		self.assertEqual(run.error_agencies, 1)
		self.assertIsNotNone(run.completed_at)
		self.assertEqual(run.checks.count(), 3)
		error_check = run.checks.get(agency__agency_url='https://error.example/Bids.aspx')
		self.assertEqual(error_check.status, 'ERROR')
		self.assertEqual(error_check.reason, 'check_failed')
		active = run.checks.get(agency__agency_url='https://active.example/Bids.aspx')
		unknown = run.checks.get(agency__agency_url='https://unknown.example/Bids.aspx')
		self.assertEqual(active.status, 'ACTIVE')
		self.assertEqual(unknown.status, 'UNKNOWN')
		self.assertEqual(
			active.agency.container_selector,
			'div.bidItems.listItems',
		)

	@patch(
		'monitors.management.commands.check_agencies.load_site_urls',
		return_value=['https://no-bids.example/Bids.aspx'],
	)
	@patch('monitors.management.commands.check_agencies.check_agency')
	def test_command_reuses_todays_run_and_reports_summary(
		self,
		check_agency_mock,
		_load_urls,
	):
		check_agency_mock.return_value = CheckResult('NO_BID', 'no_bids_phrase')

		out = io.StringIO()
		call_command('check_agencies', stdout=out)
		first_run_id = MonitorRun.objects.get().id
		call_command('check_agencies', stdout=out)

		self.assertEqual(MonitorRun.objects.count(), 1)
		self.assertEqual(MonitorRun.objects.get().id, first_run_id)
		self.assertEqual(MonitorRun.objects.get().checks.count(), 1)
		self.assertIn('Checked 1, Active 0, No bid 1, Unknown 0, Errors 0', out.getvalue())
		self.assertIn(
			'[1/1] no-bids.example: NO_BID (no_bids_phrase)',
			out.getvalue(),
		)


class DailyReportViewTests(TestCase):
	def setUp(self):
		self.run = MonitorRun.objects.create(
			run_date=timezone.localdate(),
			started_at=timezone.now(),
			completed_at=timezone.now(),
			total_agencies=3,
			active_agencies=2,
			no_bid_agencies=1,
		)

	def add_check(self, name, url, status, entries_found=0, reason='test_reason'):
		agency = AgencyMonitor.objects.create(
			agency_name=name,
			ecgains=name.lower().replace(' ', '-'),
			agency_url=url,
			container_selector='.bids',
		)
		return AgencyCheck.objects.create(
			run=self.run,
			agency=agency,
			status=status,
			broken_at_check=False,
			entries_found=entries_found,
			reason=reason,
		)

	def test_daily_report_groups_and_sorts_active_and_no_bid_sites(self):
		self.add_check('Few Bids', 'https://few.example', 'ACTIVE', 2)
		self.add_check('Most Bids', 'https://most.example', 'ACTIVE', 12)
		self.add_check('No Bids', 'https://none.example', 'NO_BID', 0)

		response = self.client.get('/')

		self.assertEqual(response.status_code, 200)
		self.assertTemplateUsed(response, 'monitors/daily_report.html')
		active_checks = response.context['active_checks']
		self.assertEqual(
			[check.agency.agency_name for check in active_checks],
			['Most Bids', 'Few Bids'],
		)
		self.assertEqual(
			[check.agency.agency_name for check in response.context['no_bid_checks']],
			['No Bids'],
		)
		self.assertContains(response, 'Active bids (2)')
		self.assertContains(response, 'No-bid sites (1)')

	def test_daily_report_shows_empty_state_without_todays_run(self):
		self.run.delete()

		response = self.client.get('/')

		self.assertEqual(response.status_code, 200)
		self.assertIsNone(response.context['run'])
		self.assertContains(response, 'No monitoring run is recorded')
		self.assertContains(response, 'No active bids reported today.')


class FakeResponse:
	def __init__(self, status_code=200, chunks=None, headers=None, encoding='utf-8'):
		self.status_code = status_code
		self.chunks = chunks or [b'<html>agency</html>']
		self.headers = headers or {}
		self.encoding = encoding
		self.closed = False

	def iter_content(self, chunk_size):
		yield from self.chunks

	def close(self):
		self.closed = True


class FakeSession:
	def __init__(self, outcomes):
		self.outcomes = list(outcomes)
		self.headers = {}
		self.max_redirects = None
		self.calls = []
		self.closed = False

	def get(self, url, **kwargs):
		self.calls.append((url, kwargs))
		outcome = self.outcomes.pop(0)
		if isinstance(outcome, Exception):
			raise outcome
		return outcome

	def close(self):
		self.closed = True


class FetchPageTests(SimpleTestCase):
	def make_session(self, outcomes):
		session = FakeSession(outcomes)
		patcher = patch('monitors.services.fetcher.requests.Session', return_value=session)
		patcher.start()
		self.addCleanup(patcher.stop)
		return session

	@patch('monitors.services.fetcher.time.sleep')
	def test_http_success_sets_request_limits_and_user_agent(self, _sleep):
		response = FakeResponse()
		session = self.make_session([response])

		result = fetch_page('https://agency.example/bids')

		self.assertEqual(result, FetchResult('<html>agency</html>', 200, None))
		self.assertEqual(session.headers['User-Agent'], USER_AGENT)
		self.assertEqual(session.max_redirects, MAX_REDIRECTS)
		self.assertEqual(session.calls[0][1]['timeout'], (10, 20))
		self.assertTrue(response.closed)
		self.assertTrue(session.closed)

	@patch('monitors.services.fetcher.time.sleep')
	def test_timeout_retries_twice_then_succeeds(self, sleep):
		session = self.make_session([
			requests.Timeout(),
			requests.Timeout(),
			FakeResponse(),
		])

		result = fetch_page('https://agency.example/bids')

		self.assertEqual(result.status_code, 200)
		self.assertIsNone(result.error)
		self.assertEqual(len(session.calls), 3)
		self.assertEqual([call.args[0] for call in sleep.call_args_list], [0.5, 1.0])

	@patch('monitors.services.fetcher.time.sleep')
	def test_exhausted_timeouts_return_error(self, _sleep):
		session = self.make_session([
			requests.Timeout(),
			requests.Timeout(),
			requests.Timeout(),
		])

		result = fetch_page('https://agency.example/bids')

		self.assertEqual(result.error, 'timeout')
		self.assertEqual(len(session.calls), 3)

	@patch('monitors.services.fetcher.time.sleep')
	def test_server_error_retries_twice(self, sleep):
		session = self.make_session([
			FakeResponse(status_code=503),
			FakeResponse(status_code=503),
			FakeResponse(status_code=503),
		])

		result = fetch_page('https://agency.example/bids')

		self.assertEqual((result.status_code, result.error), (503, 'http_503'))
		self.assertEqual(len(session.calls), 3)
		self.assertEqual(sleep.call_count, 2)

	@patch('monitors.services.fetcher.time.sleep')
	def test_client_error_does_not_retry(self, _sleep):
		session = self.make_session([FakeResponse(status_code=404)])

		result = fetch_page('https://agency.example/missing')

		self.assertEqual((result.status_code, result.error), (404, 'http_404'))
		self.assertEqual(len(session.calls), 1)

	@patch('monitors.services.fetcher.time.sleep')
	def test_dns_error_is_returned_without_retry(self, _sleep):
		session = self.make_session([
			requests.ConnectionError('NameResolutionError: Failed to resolve host'),
		])

		result = fetch_page('https://missing.invalid/bids')

		self.assertEqual(result.error, 'dns')
		self.assertEqual(len(session.calls), 1)

	@patch('monitors.services.fetcher.MAX_RESPONSE_BYTES', 4)
	@patch('monitors.services.fetcher.time.sleep')
	def test_oversized_response_is_rejected(self, _sleep):
		self.make_session([FakeResponse(chunks=[b'12345'])])

		result = fetch_page('https://agency.example/bids')

		self.assertEqual(result.error, 'too_large')

	@patch('monitors.services.fetcher._create_browser')
	@patch('monitors.services.fetcher._fetch_http')
	def test_browser_mode_returns_rendered_html(self, fetch_http, create_browser):
		fetch_http.return_value = FetchResult('<html>static</html>', 200, None)
		driver = Mock()
		driver.page_source = '<html>rendered</html>'
		create_browser.return_value = driver

		result = fetch_page('https://agency.example/bids', fetch_mode='browser')

		self.assertEqual(result, FetchResult('<html>rendered</html>', 200, None))
		driver.set_page_load_timeout.assert_called_once_with(20)
		driver.get.assert_called_once_with('https://agency.example/bids')
		driver.quit.assert_called_once_with()

	@patch('monitors.services.fetcher._create_browser')
	@patch('monitors.services.fetcher._fetch_http')
	def test_browser_mode_attempts_rendering_after_http_403(self, fetch_http, create_browser):
		fetch_http.return_value = FetchResult(None, 403, 'http_403')
		driver = Mock()
		driver.page_source = '<html>browser page</html>'
		create_browser.return_value = driver

		result = fetch_page('https://agency.example/bids', fetch_mode='browser')

		self.assertEqual(result, FetchResult('<html>browser page</html>', None, None))
		driver.get.assert_called_once_with('https://agency.example/bids')

	@patch('monitors.services.fetcher._create_browser')
	@patch('monitors.services.fetcher._fetch_http')
	def test_browser_mode_preserves_http_404(self, fetch_http, create_browser):
		fetch_http.return_value = FetchResult(None, 404, 'http_404')

		result = fetch_page('https://agency.example/missing', fetch_mode='browser')

		self.assertEqual(result, FetchResult(None, 404, 'http_404'))
		create_browser.assert_not_called()
