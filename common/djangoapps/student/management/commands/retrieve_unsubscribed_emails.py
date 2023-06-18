"""Management command to retrieve unsubscribed emails from Braze."""

import csv
import logging
import uuid
from datetime import datetime, timedelta

from django.contrib.auth.models import User  # lint-amnesty, pylint: disable=imported-auth-user, wrong-import-order
from django.contrib.sites.models import Site
from django.core.management.base import BaseCommand, CommandError
from edx_ace import ace
from edx_ace.recipient import Recipient

from common.djangoapps.student.message_types import RetrieveUnsubscribedEmails
from lms.djangoapps.utils import get_braze_client
from openedx.core.djangoapps.ace_common.template_context import get_base_template_context
from openedx.core.lib.celery.task_utils import emulate_http_request

logger = logging.getLogger(__name__)

UNSUBSCRIBED_EMAILS_MAX_LIMIT = 500


class Command(BaseCommand):
    """
    Management command to retrieve unsubscribed emails from Braze.
    """

    help = """
    Retrieve unsubscribed emails from Braze API based on specified parameters.

    Usage:
    python manage.py retrieve_unsubscribed_emails [--start-date START_DATE] [--end-date END_DATE]

    Options:
      --start-date START_DATE   Start date (optional)
      --end-date END_DATE       End date (optional)

    Example:
        $ ... retrieve_unsubscribed_emails --start-date 2022-01-01 --end-date 2023-01-01
    """

    def add_arguments(self, parser):
        parser.add_argument('--start-date', dest='start_date', help='Start date')
        parser.add_argument('--end-date', dest='end_date', help='End date')

    def handle(self, *args, **options):
        emails = []
        start_date = options.get('start_date')
        end_date = options.get('end_date')

        if not start_date and not end_date:
            start_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
            end_date = datetime.now().strftime('%Y-%m-%d')

        try:
            braze_client = get_braze_client()
            if braze_client:
                emails = braze_client.retrieve_unsubscribed_emails(
                    start_date=start_date,
                    end_date=end_date,
                    limit=UNSUBSCRIBED_EMAILS_MAX_LIMIT
                )
                self.stdout.write(self.style.SUCCESS('Unsubscribed emails retrieved successfully'))
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception(f'Unable to retrieve unsubscribed emails from Braze due to : {exc}')
            raise CommandError(
                f'Unable to retrieve unsubscribed emails from Braze due to : {exc}')  # lint-amnesty, pylint: disable=raise-missing-from

        output_filename = f'{str(uuid.uuid4())}.csv'

        try:
            with open(output_filename, 'w', newline='') as output_file:
                csv_writer = csv.writer(output_file)
                csv_writer.writerow(('email', 'unsubscribed_at'))
                rows = [(email['email'], email['unsubscribed_at']) for email in emails]
                csv_writer.writerows(rows)
                csv_file_path = output_file.name
                self.stdout.write(
                    self.style.SUCCESS(f'Unsubscribed emails write in CSV file {output_filename} successfully'))
        except OSError as e:  # pylint: disable=broad-except
            logger.exception(f'Error writing to file: {output_filename}')
            raise CommandError(
                f'Error writing to file: {output_filename}') from e  # lint-amnesty, pylint: disable=raise-missing-from

        try:
            site = Site.objects.get_current()
            message_context = get_base_template_context(site)
            message_context.update({
                'start_date': start_date,
                'end_date': end_date,
                'csv_file_path': csv_file_path
            })

            user = User.objects.get(pk=19)
            with emulate_http_request(site=site, user=user):
                msg = RetrieveUnsubscribedEmails().personalize(
                    recipient=Recipient(user.id, user.email),
                    language='English',
                    user_context=message_context,
                )

                ace.send(msg)
                print("\n\n\nGOT IT\n\n\n")
                logger.info('Unsubscribed emails data sent to your email.')
        except Exception:  # pylint: disable=broad-except
            logger.exception('Could not send email')
