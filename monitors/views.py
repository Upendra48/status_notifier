from django.utils import timezone
from django.shortcuts import render

from monitors.models import AgencyCheck, BidStatus, MonitorRun


def daily_report(request):
	run = (
		MonitorRun.objects.filter(run_date=timezone.localdate())
		.order_by('-started_at')
		.first()
	)
	checks = (
		AgencyCheck.objects.filter(run=run).select_related('agency')
		if run is not None
		else AgencyCheck.objects.none()
	)
	active_checks = sorted(
		(check for check in checks if check.status == BidStatus.ACTIVE),
		key=lambda check: (-check.entries_found, check.agency.agency_name.casefold()),
	)
	no_bid_checks = sorted(
		(check for check in checks if check.status == BidStatus.NO_BID),
		key=lambda check: check.agency.agency_name.casefold(),
	)
	review_checks = sorted(
		(
			check
			for check in checks
			if check.status in {BidStatus.UNKNOWN, BidStatus.ERROR}
		),
		key=lambda check: (
			check.status,
			check.agency.agency_name.casefold(),
		),
	)
	return render(
		request,
		'monitors/daily_report.html',
		{
			'run': run,
			'today': timezone.localdate(),
			'active_checks': active_checks,
			'no_bid_checks': no_bid_checks,
			'review_checks': review_checks,
			'active_count': len(active_checks),
			'no_bid_count': len(no_bid_checks),
			'review_count': len(review_checks),
		},
	)
