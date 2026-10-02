from django.contrib import admin

from .models import AgencyCheck, AgencyMonitor, MonitorRun


@admin.register(AgencyMonitor)
class AgencyMonitorAdmin(admin.ModelAdmin):
	list_display = (
		'agency_name',
		'ecgains',
		'broken',
		'monitoring_enabled',
		'last_status',
		'last_checked_at',
	)
	list_filter = ('last_status', 'broken', 'monitoring_enabled')
	search_fields = ('agency_name', 'ecgains')


class ReadOnlyModelAdmin(admin.ModelAdmin):
	def get_readonly_fields(self, request, obj=None):
		return tuple(field.name for field in self.model._meta.fields)

	def has_add_permission(self, request):
		return False

	def has_delete_permission(self, request, obj=None):
		return False


@admin.register(AgencyCheck)
class AgencyCheckAdmin(ReadOnlyModelAdmin):
	list_display = (
		'agency',
		'run',
		'status',
		'broken_at_check',
		'container_found',
		'entries_found',
		'dates_parsed',
		'checked_at',
	)
	list_filter = ('status', 'broken_at_check', 'container_found')


@admin.register(MonitorRun)
class MonitorRunAdmin(ReadOnlyModelAdmin):
	list_display = (
		'run_date',
		'started_at',
		'completed_at',
		'total_agencies',
		'active_agencies',
		'no_bid_agencies',
		'unknown_agencies',
		'error_agencies',
		'notification_sent',
	)
	list_filter = ('notification_sent',)
