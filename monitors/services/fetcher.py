from dataclasses import dataclass
import socket
import time

import requests
from selenium.common.exceptions import TimeoutException, WebDriverException


USER_AGENT = 'BidNotifier/1.0 (public bid availability monitor)'
CONNECT_TIMEOUT_SECONDS = 10
READ_TIMEOUT_SECONDS = 20
MAX_RETRIES = 2
BACKOFF_SECONDS = 0.5
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 5
CHUNK_SIZE = 64 * 1024


@dataclass(frozen=True)
class FetchResult:
	html: str | None
	status_code: int | None
	error: str | None


def fetch_page(url: str, fetch_mode: str = 'http') -> FetchResult:
	if fetch_mode not in {'http', 'browser'}:
		return FetchResult(None, None, 'unsupported_fetch_mode')

	try:
		http_result = _fetch_http(url)
		if fetch_mode == 'http':
			return http_result
		if (
			http_result.status_code is not None
			and 400 <= http_result.status_code < 500
			and http_result.status_code != 403
		):
			return http_result

		browser_status = None if http_result.error else http_result.status_code
		browser_result = _fetch_with_browser(url, browser_status)
		if browser_result.error and http_result.error:
			return http_result
		return browser_result
	except Exception:
		return FetchResult(None, None, 'request_error')


def _fetch_http(url: str) -> FetchResult:
	session = requests.Session()
	session.headers.update({'User-Agent': USER_AGENT})
	session.max_redirects = MAX_REDIRECTS

	try:
		for attempt in range(MAX_RETRIES + 1):
			response = None
			try:
				response = session.get(
					url,
					timeout=(CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS),
					allow_redirects=True,
					stream=True,
				)
				status_code = response.status_code

				if 500 <= status_code < 600:
					if attempt < MAX_RETRIES:
						_backoff(attempt)
						continue
					return FetchResult(None, status_code, f'http_{status_code}')

				if not 200 <= status_code < 300:
					return FetchResult(None, status_code, f'http_{status_code}')

				content_length = response.headers.get('Content-Length')
				if content_length and int(content_length) > MAX_RESPONSE_BYTES:
					return FetchResult(None, status_code, 'too_large')

				content = bytearray()
				for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
					if not chunk:
						continue
					content.extend(chunk)
					if len(content) > MAX_RESPONSE_BYTES:
						return FetchResult(None, status_code, 'too_large')

				encoding = response.encoding or 'utf-8'
				return FetchResult(content.decode(encoding, errors='replace'), status_code, None)
			except requests.Timeout:
				if attempt < MAX_RETRIES:
					_backoff(attempt)
					continue
				return FetchResult(None, None, 'timeout')
			except requests.TooManyRedirects:
				return FetchResult(None, None, 'too_many_redirects')
			except requests.ConnectionError as exc:
				return FetchResult(None, None, _connection_error_reason(exc))
			except requests.RequestException:
				return FetchResult(None, None, 'request_error')
			finally:
				if response is not None:
					response.close()

		return FetchResult(None, None, 'request_error')
	finally:
		session.close()


def _fetch_with_browser(url: str, status_code: int | None) -> FetchResult:
	for attempt in range(MAX_RETRIES + 1):
		driver = None
		try:
			driver = _create_browser()
			driver.set_page_load_timeout(READ_TIMEOUT_SECONDS)
			driver.get(url)
			html = driver.page_source or ''
			if len(html.encode('utf-8')) > MAX_RESPONSE_BYTES:
				return FetchResult(None, status_code, 'too_large')
			return FetchResult(html, status_code, None)
		except TimeoutException:
			if attempt < MAX_RETRIES:
				_backoff(attempt)
				continue
			return FetchResult(None, status_code, 'timeout')
		except WebDriverException as exc:
			if 'timeout' in str(exc).lower():
				if attempt < MAX_RETRIES:
					_backoff(attempt)
					continue
				return FetchResult(None, status_code, 'timeout')
			return FetchResult(None, status_code, 'browser_error')
		except Exception:
			return FetchResult(None, status_code, 'browser_error')
		finally:
			if driver is not None:
				try:
					driver.quit()
				except Exception:
					pass

	return FetchResult(None, status_code, 'browser_error')


def _create_browser():
	from seleniumbase import Driver

	return Driver(browser='chrome', headless=True, agent=USER_AGENT)


def _backoff(attempt: int) -> None:
	time.sleep(BACKOFF_SECONDS * (2 ** attempt))


def _connection_error_reason(error: requests.ConnectionError) -> str:
	current = error
	while current is not None:
		if isinstance(current, socket.gaierror):
			return 'dns'
		current = current.__cause__ or current.__context__

	message = repr(error).lower()
	dns_markers = (
		'nameresolutionerror',
		'failed to resolve',
		'getaddrinfo failed',
		'name or service not known',
		'nodename nor servname',
	)
	return 'dns' if any(marker in message for marker in dns_markers) else 'connection_error'
