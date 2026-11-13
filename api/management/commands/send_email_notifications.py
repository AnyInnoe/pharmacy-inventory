import smtplib
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from api.models import EmailNotification


MAX_ATTEMPTS = 5
STALE_SEND_MINUTES = 15


class EmailDeliveryError(Exception):
    pass


class Command(BaseCommand):
    help = "Deliver queued pharmacy email notifications and schedule retries."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=25)

    def handle(self, *args, **options):
        limit = options["limit"]
        if limit < 1:
            raise ValueError("--limit must be a positive integer.")

        now = timezone.now()
        stale_before = now - timedelta(minutes=STALE_SEND_MINUTES)
        stale = EmailNotification.objects.filter(
            status=EmailNotification.Status.SENDING,
            processing_started_at__lt=stale_before,
        )
        for notification in stale:
            notification.status = (
                EmailNotification.Status.FAILED
                if notification.attempts >= MAX_ATTEMPTS
                else EmailNotification.Status.PENDING
            )
            notification.processing_started_at = None
            notification.next_attempt_at = now
            notification.last_error = "Email worker stopped before recording a delivery result."
            notification.save(update_fields=[
                "status",
                "processing_started_at",
                "next_attempt_at",
                "last_error",
            ])

        queued_ids = list(
            EmailNotification.objects.filter(
                status=EmailNotification.Status.PENDING,
                next_attempt_at__lte=now,
            ).order_by("created_at", "id").values_list("id", flat=True)[:limit]
        )
        sent = 0
        failed = 0
        for notification_id in queued_ids:
            with transaction.atomic():
                notification = EmailNotification.objects.select_for_update().get(
                    pk=notification_id,
                )
                if (
                    notification.status != EmailNotification.Status.PENDING
                    or notification.next_attempt_at > now
                ):
                    continue
                notification.status = EmailNotification.Status.SENDING
                notification.attempts += 1
                notification.processing_started_at = now
                notification.save(update_fields=[
                    "status",
                    "attempts",
                    "processing_started_at",
                ])

            try:
                delivered = send_mail(
                    notification.subject,
                    notification.body,
                    settings.DEFAULT_FROM_EMAIL,
                    [notification.recipient_email],
                    fail_silently=False,
                )
                if delivered != 1:
                    raise EmailDeliveryError("The email backend did not confirm delivery.")
            except (EmailDeliveryError, OSError, smtplib.SMTPException, TimeoutError) as error:
                with transaction.atomic():
                    notification = EmailNotification.objects.select_for_update().get(
                        pk=notification_id,
                    )
                    notification.last_error = str(error)[:2000]
                    notification.processing_started_at = None
                    if notification.attempts >= MAX_ATTEMPTS:
                        notification.status = EmailNotification.Status.FAILED
                    else:
                        retry_seconds = min(60 * (2 ** (notification.attempts - 1)), 21600)
                        notification.status = EmailNotification.Status.PENDING
                        notification.next_attempt_at = timezone.now() + timedelta(
                            seconds=retry_seconds,
                        )
                    notification.save(update_fields=[
                        "status",
                        "processing_started_at",
                        "last_error",
                        "next_attempt_at",
                    ])
                failed += 1
                continue

            with transaction.atomic():
                notification = EmailNotification.objects.select_for_update().get(
                    pk=notification_id,
                )
                notification.status = EmailNotification.Status.SENT
                notification.sent_at = timezone.now()
                notification.processing_started_at = None
                notification.last_error = ""
                notification.save(update_fields=[
                    "status",
                    "sent_at",
                    "processing_started_at",
                    "last_error",
                ])
            sent += 1

        self.stdout.write(
            self.style.SUCCESS(f"Email notifications sent: {sent}; failed attempts: {failed}.")
        )
