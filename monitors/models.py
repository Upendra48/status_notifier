from django.db import models


class BidStatus(models.TextChoices):
	ACTIVE = 'ACTIVE', 'Active'
	NO_BID = 'NO_BID', 'No bid'
	UNKNOWN = 'UNKNOWN', 'Unknown'
	ERROR = 'ERROR', 'Error'


class BidSource(models.Model):
	id = models.BigAutoField(primary_key=True)
	ecgains = models.CharField(max_length=50)
	agency_name = models.CharField(max_length=255)
	agency_url = models.TextField()
	broken = models.BooleanField(default=True)

	class Meta:
		managed = False
		db_table = 'bids'


class BidStatusRecord(models.Model):
	id = models.BigAutoField(primary_key=True)
	bid_id = models.BigIntegerField(unique=True)
	spider_status = models.CharField(max_length=20, default='UNKNOWN')
	active_status = models.CharField(
		max_length=20,
		choices=BidStatus.choices,
		default=BidStatus.UNKNOWN,
	)
	repair_requested = models.BooleanField(default=False)
	repair_requested_at = models.DateTimeField(null=True, blank=True)
	repair_completed = models.BooleanField(default=False)
	repaired_at = models.DateTimeField(null=True, blank=True)
	last_checked_at = models.DateTimeField(null=True, blank=True)
	last_error = models.TextField(null=True, blank=True)
	notes = models.TextField(null=True, blank=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		managed = False
		db_table = 'bid_status'


class AgencyMonitor(models.Model):
	agency_name = models.CharField(max_length=255)
	ecgains = models.CharField(max_length=50, unique=True)
	agency_url = models.URLField()

	container_selector = models.TextField()
	bid_selector = models.TextField(blank=True)
	due_date_selector = models.TextField(blank=True)
	date_format = models.CharField(max_length=100, blank=True)
	timezone = models.CharField(max_length=64, default='America/New_York')
	no_bid_phrase = models.CharField(max_length=255, blank=True)

	fetch_mode = models.CharField(max_length=10, default='http')
	notes = models.TextField(blank=True)

	broken = models.BooleanField(default=True)
	monitoring_enabled = models.BooleanField(default=True)

	last_status = models.CharField(
		max_length=20,
		choices=BidStatus.choices,
		default=BidStatus.UNKNOWN,
	)
	last_checked_at = models.DateTimeField(null=True, blank=True)
	last_error = models.TextField(blank=True)

	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)


class MonitorRun(models.Model):
	run_date = models.DateField()
	started_at = models.DateTimeField()
	completed_at = models.DateTimeField(null=True, blank=True)

	total_agencies = models.IntegerField(default=0)
	active_agencies = models.IntegerField(default=0)
	no_bid_agencies = models.IntegerField(default=0)
	unknown_agencies = models.IntegerField(default=0)
	error_agencies = models.IntegerField(default=0)

class AgencyCheck(models.Model):
	run = models.ForeignKey(MonitorRun, on_delete=models.CASCADE, related_name='checks')
	agency = models.ForeignKey(AgencyMonitor, on_delete=models.CASCADE, related_name='checks')

	status = models.CharField(max_length=20, choices=BidStatus.choices)
	broken_at_check = models.BooleanField()
	container_found = models.BooleanField(default=False)
	entries_found = models.IntegerField(default=0)
	dates_parsed = models.IntegerField(default=0)
	reason = models.CharField(max_length=255, blank=True)
	error = models.TextField(blank=True)
	duration_ms = models.IntegerField(null=True, blank=True)
	checked_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		constraints = [
			models.UniqueConstraint(
				fields=('run', 'agency'),
				name='unique_agency_check_per_run',
			),
		]
