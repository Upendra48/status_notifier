import json
from pathlib import Path
from urllib.parse import urlparse

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.text import slugify

from monitors.models import AgencyMonitor, BidStatus, MonitorRun
from monitors.services.monitor import CheckResult, check_agency, save_check_result


SITE_LIST_PATH = Path(__file__).resolve().parents[2] / 'site.json'
CONTAINER_SELECTOR = 'div.bidItems.listItems'
BID_SELECTOR = 'div.listItemsRow.bid'
NO_BID_PHRASE = 'There are no open bid postings at this time.'


def load_site_urls() -> list[str]:
	try:
		urls = json.loads(SITE_LIST_PATH.read_text(encoding='utf-8'))
	except (OSError, json.JSONDecodeError) as exc:
		raise CommandError(f'Could not load site list {SITE_LIST_PATH}: {exc}') from exc

	if not isinstance(urls, list) or any(
		not isinstance(url, str) or not url.strip()
		for url in urls
	):
		raise CommandError(f'{SITE_LIST_PATH} must contain a JSON list of non-empty URLs.')
	return urls


def get_or_create_site_agency(url: str) -> AgencyMonitor:
	agency = AgencyMonitor.objects.filter(agency_url=url).first()
	if agency is not None:
		return agency

	host = urlparse(url).hostname
	if not host:
		raise ValueError(f'URL has no hostname: {url}')

	identifier = slugify(urlparse(url).netloc + urlparse(url).path)[:50]
	if not identifier:
		raise ValueError(f'Could not create an agency identifier for URL: {url}')

	return AgencyMonitor.objects.create(
		agency_name=host,
		ecgains=identifier,
		agency_url=url,
		container_selector=CONTAINER_SELECTOR,
		bid_selector=BID_SELECTOR,
		no_bid_phrase=NO_BID_PHRASE,
	)


class Command(BaseCommand):
	help = 'Check the sites listed in monitors/site.json and record their results.'

	def handle(self, *args, **options):
		urls = load_site_urls()
		today = timezone.localdate()
		run, _ = MonitorRun.objects.get_or_create(
			run_date=today,
			defaults={'started_at': timezone.now()},
		)
		notify_agencies = []
		review_agencies = []
		total = len(urls)

		for index, url in enumerate(urls, start=1):
			agency = None
			try:
				agency = get_or_create_site_agency(url)
				result = check_agency(agency)
			except Exception as exc:
				error = str(exc) or exc.__class__.__name__
				result = CheckResult(
					status=BidStatus.ERROR,
					reason='check_failed',
					error=error,
				)
				agency = AgencyMonitor.objects.filter(agency_url=url).first()
				if agency is not None:
					try:
						save_check_result(run, agency, result)
					except Exception as save_exc:
						self.stderr.write(
							f'[{index}/{total}] {url}: could not save error result: '
							f'{save_exc}'
						)
				self.stderr.write(f'[{index}/{total}] {url}: {result.error}')
			else:
				try:
					save_check_result(run, agency, result)
				except Exception as exc:
					result = CheckResult(
						status=BidStatus.ERROR,
						reason='save_failed',
						container_found=result.container_found,
						entries_found=result.entries_found,
						dates_parsed=result.dates_parsed,
						error=str(exc) or exc.__class__.__name__,
						duration_ms=result.duration_ms,
					)
					self.stderr.write(
						f'[{index}/{total}] {agency.agency_name}: '
						f'could not save check result: {result.error}'
					)

			name = agency.agency_name if agency is not None else url
			self.stdout.write(
				f'[{index}/{total}] {name}: {result.status} ({result.reason})'
			)

			if agency is not None and agency.broken:
				if result.status == BidStatus.ACTIVE:
					notify_agencies.append(agency)
				elif result.status in {BidStatus.UNKNOWN, BidStatus.ERROR}:
					review_agencies.append(agency)

		run.total_agencies = total
		run.active_agencies = run.checks.filter(
			status=BidStatus.ACTIVE,
		).values('agency_id').distinct().count()
		run.no_bid_agencies = run.checks.filter(
			status=BidStatus.NO_BID,
		).values('agency_id').distinct().count()
		run.unknown_agencies = run.checks.filter(
			status=BidStatus.UNKNOWN,
		).values('agency_id').distinct().count()
		run.error_agencies = run.checks.filter(
			status=BidStatus.ERROR,
		).values('agency_id').distinct().count()
		run.completed_at = timezone.now()
		run.save(update_fields=(
			'total_agencies',
			'active_agencies',
			'no_bid_agencies',
			'unknown_agencies',
			'error_agencies',
			'completed_at',
		))

		self.stdout.write(
			self.style.SUCCESS(
				f'Checked {total}, Active {run.active_agencies}, '
				f'No bid {run.no_bid_agencies}, Unknown {run.unknown_agencies}, '
				f'Errors {run.error_agencies}'
			)
		)
		self.stdout.write(
			f'Notify list: {len(notify_agencies)}; '
			f'Review list: {len(review_agencies)}'
		)
