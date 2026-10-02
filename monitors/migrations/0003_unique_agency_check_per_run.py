from django.db import migrations, models
from django.db.models import Count


def remove_duplicate_checks(apps, schema_editor):
	AgencyCheck = apps.get_model('monitors', 'AgencyCheck')
	database = schema_editor.connection.alias
	duplicates = (
		AgencyCheck.objects.using(database)
		.values('run_id', 'agency_id')
		.annotate(check_count=Count('id'))
		.filter(check_count__gt=1)
	)

	for duplicate in duplicates.iterator():
		checks = AgencyCheck.objects.using(database).filter(
			run_id=duplicate['run_id'],
			agency_id=duplicate['agency_id'],
		).order_by('-checked_at', '-pk')
		checks.exclude(pk=checks.first().pk).delete()


class Migration(migrations.Migration):

	dependencies = [
		('monitors', '0002_alter_agencycheck_id_alter_agencymonitor_id_and_more'),
	]

	operations = [
		migrations.RunPython(remove_duplicate_checks, migrations.RunPython.noop),
		migrations.AddConstraint(
			model_name='agencycheck',
			constraint=models.UniqueConstraint(
				fields=('run', 'agency'),
				name='unique_agency_check_per_run',
			),
		),
	]
