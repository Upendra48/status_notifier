from dataclasses import dataclass, replace
from time import perf_counter

from django.db import transaction
from django.utils import timezone
from lxml.html import HtmlElement

from monitors.models import AgencyCheck, AgencyMonitor, BidStatus, MonitorRun
from monitors.services.bid_detector import find_entries
from monitors.services.container import find_container
from monitors.services.fetcher import fetch_page


_OPEN_STATUS = 'open'
_CLOSED_STATUSES = {
	'awarded',
	'canceled',
	'cancelled',
	'closed',
	'complete',
	'completed',
	'expired',
	'withdrawn',
}


@dataclass(frozen=True)
class CheckResult:
	status: str
	reason: str
	container_found: bool = False
	entries_found: int = 0
	dates_parsed: int = 0
	error: str = ''
	duration_ms: int = 0


def check_agency(agency: AgencyMonitor) -> CheckResult:
	started_at = perf_counter()
	try:
		fetch_result = fetch_page(agency.agency_url, agency.fetch_mode)
		if fetch_result.error or fetch_result.html is None:
			return _with_duration(
				CheckResult(
					BidStatus.ERROR,
					'fetch_failed',
					error=fetch_result.error or 'empty_response',
				),
				started_at,
			)

		container, container_reason = find_container(
			fetch_result.html,
			agency.container_selector,
		)
		if container is None:
			return _with_duration(
				CheckResult(
					BidStatus.UNKNOWN,
					'container_missing',
					error=container_reason or '',
				),
				started_at,
			)

		entries = find_entries(container, agency.bid_selector)
		if not entries:
			if _matches_no_bid_phrase(container, agency.no_bid_phrase):
				return _with_duration(
					CheckResult(BidStatus.NO_BID, 'no_bids_phrase', True),
					started_at,
				)
			return _with_duration(
				CheckResult(BidStatus.UNKNOWN, 'no_entries', True),
				started_at,
			)

		entry_statuses = [_entry_status(entry) for entry in entries]
		if _OPEN_STATUS in entry_statuses:
			return _with_duration(
				CheckResult(
					BidStatus.ACTIVE,
					'open_bid_found',
					True,
					len(entries),
				),
				started_at,
			)
		if any(status in _CLOSED_STATUSES for status in entry_statuses):
			return _with_duration(
				CheckResult(BidStatus.NO_BID, 'no_open_bids', True, len(entries)),
				started_at,
			)
		return _with_duration(
			CheckResult(BidStatus.UNKNOWN, 'status_not_found', True, len(entries)),
			started_at,
		)
	except Exception as exc:
		return _with_duration(
			CheckResult(
				BidStatus.ERROR,
				'processing_error',
				error=str(exc) or exc.__class__.__name__,
			),
			started_at,
		)


def save_check_result(
	run: MonitorRun,
	agency: AgencyMonitor,
	result: CheckResult,
) -> AgencyCheck:
	checked_at = timezone.now()
	with transaction.atomic():
		check, _ = AgencyCheck.objects.update_or_create(
			run=run,
			agency=agency,
			defaults={
				'status': result.status,
				'broken_at_check': agency.broken,
				'container_found': result.container_found,
				'entries_found': result.entries_found,
				'dates_parsed': result.dates_parsed,
				'reason': result.reason,
				'error': result.error,
				'duration_ms': result.duration_ms,
				'checked_at': checked_at,
			},
		)
		agency.last_status = result.status
		agency.last_checked_at = checked_at
		agency.last_error = result.error
		agency.save(update_fields=('last_status', 'last_checked_at', 'last_error', 'updated_at'))
	return check


def _with_duration(result: CheckResult, started_at: float) -> CheckResult:
	duration_ms = max(0, round((perf_counter() - started_at) * 1000))
	return replace(result, duration_ms=duration_ms)


def _matches_no_bid_phrase(container: HtmlElement, phrase: str) -> bool:
	return bool(phrase and phrase.casefold() in container.text_content().casefold())


def _entry_status(entry: HtmlElement) -> str | None:
	status_values = {
		_OPEN_STATUS,
		*_CLOSED_STATUSES,
	}
	for element in entry.iter():
		if not isinstance(element.tag, str):
			continue
		value = ' '.join(element.text_content().split()).casefold()
		if value in status_values:
			return value
	return None