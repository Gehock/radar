import logging
import time

from django.core.management.base import BaseCommand
from django.conf import settings

from data.files import acquire_lock
from data.models import Course, Submission
from matcher.matcher import match
from radar.config import provider_config, configured_function
from tokenizer.tokenizer import tokenize_submission


logger = logging.getLogger("radar.cron")

class Command(BaseCommand):
    args = ""
    help = "Cron work for new submissions: provide, tokenize, match"

    def handle(self, *args, **options):
        lock = acquire_lock()
        if lock is None:
            logger.info("Cannot get manage lock, another process running.")
            return

        start = time.time()
        for course in Course.objects.filter(archived=False):

            # Run provider tasks.
            p_config = provider_config(course.provider)
            f = configured_function(p_config, "cron")
            f(course, p_config)

            invalid_submissions = []
            # Tokenize and match new and valid submissions.
            for submission in Submission.objects.filter(
                    exercise__course=course, exercise__paused=False,
                    tokens__isnull=True):
                if not tokenize_submission(submission, p_config):
                    invalid_submissions.append(submission)
                    continue
                if (not match(submission)
                    or (settings.CRON_STOP_SECONDS is not None
                        and time.time() - start > settings.CRON_STOP_SECONDS)):
                    return

            # Delete all new submissions that could not be tokenized.
            for submission in invalid_submissions:
                submission.delete()

            # Check again for yet unmatched submissions.
            for submission in Submission.objects.filter(
                    exercise__course=course, exercise__paused=False,
                    max_similarity__isnull=True):
                if (not match(submission)
                    or (settings.CRON_STOP_SECONDS is not None
                        and time.time() - start > settings.CRON_STOP_SECONDS)):
                    return
