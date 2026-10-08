from django.utils import timezone
from django.views.generic import TemplateView

from monitors.models import AgencyCheck, MonitorRun
from monitors.services.report import get_report_category


class DailyReportView(TemplateView):
	template_name = 'monitors/daily_report.html'

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		today = timezone.localdate()
		run = (
			MonitorRun.objects.filter(run_date=today)
			.order_by('-started_at')
			.first()
		)
		checks = (
			AgencyCheck.objects.filter(run=run).select_related('agency')
			if run is not None
			else AgencyCheck.objects.none()
		)
		active_checks = sorted(
			(
				check for check in checks
				if get_report_category(check.status, check.broken_at_check) == 'active'
			),
			key=lambda check: (
				-check.entries_found,
				check.agency.agency_name.casefold(),
			),
		)
		no_bid_checks = sorted(
			(
				check for check in checks
				if get_report_category(check.status, check.broken_at_check) == 'no_bid'
			),
			key=lambda check: check.agency.agency_name.casefold(),
		)
		review_checks = sorted(
			(
				check
				for check in checks
				if get_report_category(check.status, check.broken_at_check) == 'review'
			),
			key=lambda check: (
				check.status,
				check.agency.agency_name.casefold(),
			),
		)
		logged_checks = sorted(
			(
				check for check in checks
				if get_report_category(check.status, check.broken_at_check) == 'logged'
			),
			key=lambda check: (
				check.status,
				check.agency.agency_name.casefold(),
			),
		)
		context.update({
			'run': run,
			'today': today,
			'active_checks': active_checks,
			'no_bid_checks': no_bid_checks,
			'review_checks': review_checks,
			'logged_checks': logged_checks,
			'active_count': len(active_checks),
			'no_bid_count': len(no_bid_checks),
			'review_count': len(review_checks),
			'logged_count': len(logged_checks),
		})
		return context
