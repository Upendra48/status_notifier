from datetime import datetime
from typing import TypedDict

from django.core.management.base import BaseCommand, CommandError
from django.db import DEFAULT_DB_ALIAS, transaction
from django.utils import timezone

from monitors.models import (
	AgencyMonitor,
	BidSource,
	BidStatus,
	BidStatusRecord,
	MonitorRun,
)
from monitors.services.monitor import CheckResult, check_agency, save_check_result


CONTAINER_SELECTOR = 'div.bidItems.listItems'
BID_SELECTOR = 'div.listItemsRow.bid'
NO_BID_PHRASE = 'There are no open bid postings at this time.'


class StatusUpdates(TypedDict):
	spider_status: str
	active_status: str
	last_checked_at: datetime
	last_error: str | None


def load_bids() -> list[BidSource]:
	bids = list(
		BidSource.objects.using(DEFAULT_DB_ALIAS).order_by('id')
	)
	seen_ecgains: set[str] = set()
	for bid in bids:
		if not bid.ecgains.strip():
			raise CommandError(f'Bid {bid.pk} has an empty EC Gains identifier.')
		normalized_ecgains = bid.ecgains.casefold()
		if normalized_ecgains in seen_ecgains:
			raise CommandError(
				f'Duplicate EC Gains identifier {bid.ecgains!r} in the bids table.'
			)
		if not bid.agency_name.strip():
			raise CommandError(f'Bid {bid.pk} has an empty agency name.')
		if not bid.agency_url.strip():
			raise CommandError(f'Bid {bid.pk} has an empty agency URL.')
		seen_ecgains.add(normalized_ecgains)
	return bids


def get_or_create_bid_agency(bid: BidSource) -> AgencyMonitor:
	agency, created = AgencyMonitor.objects.get_or_create(
		ecgains=bid.ecgains,
		defaults={
			'agency_name': bid.agency_name,
			'agency_url': bid.agency_url,
			'container_selector': CONTAINER_SELECTOR,
			'bid_selector': BID_SELECTOR,
			'no_bid_phrase': NO_BID_PHRASE,
			'broken': bid.broken,
		},
	)
	if not created:
		changed_fields = []
		for field, value in (
			('agency_name', bid.agency_name),
			('agency_url', bid.agency_url),
			('broken', bid.broken),
		):
			if getattr(agency, field) != value:
				setattr(agency, field, value)
				changed_fields.append(field)
		if changed_fields:
			agency.save(update_fields=(*changed_fields, 'updated_at'))
	return agency


def get_status_updates(result: CheckResult) -> StatusUpdates:
	successful = result.status in {BidStatus.ACTIVE, BidStatus.NO_BID}
	return {
		'spider_status': 'SUCCESS' if successful else 'ERROR',
		'active_status': result.status,
		'last_checked_at': timezone.now(),
		'last_error': (
			result.error or result.reason
			if not successful
			else None
		),
	}


def update_bid_status(bid: BidSource, result: CheckResult) -> None:
	updates = get_status_updates(result)
	BidStatusRecord.objects.using(DEFAULT_DB_ALIAS).update_or_create(
		bid_id=bid.pk,
		defaults={
			'spider_status': updates['spider_status'],
			'active_status': updates['active_status'],
			'last_checked_at': updates['last_checked_at'],
			'last_error': updates['last_error'],
		},
	)


class Command(BaseCommand):
	help = 'Check the bids listed in the local bids table and record their results.'

	def handle(self, *args, **options):
		bids = load_bids()
		today = timezone.localdate()
		total = len(bids)
		run = MonitorRun.objects.create(
			run_date=today,
			started_at=timezone.now(),
			total_agencies=total,
		)

		for index, bid in enumerate(bids, start=1):
			agency = get_or_create_bid_agency(bid)
			try:
				result = check_agency(agency)
			except Exception as exc:
				error = str(exc) or exc.__class__.__name__
				result = CheckResult(
					status=BidStatus.ERROR,
					reason='check_failed',
					error=error,
				)
				self.stderr.write(
					f'[{index}/{total}] {agency.agency_name}: {result.error}'
				)

			with transaction.atomic(using=DEFAULT_DB_ALIAS):
				save_check_result(run, agency, result)
				update_bid_status(bid, result)

			self.stdout.write(
				f'[{index}/{total}] {agency.agency_name}: '
				f'{result.status} ({result.reason})'
			)

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
