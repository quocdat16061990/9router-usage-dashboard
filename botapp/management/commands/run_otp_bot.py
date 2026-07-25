from django.core.management.base import BaseCommand

from botapp.bot import run_bot


class Command(BaseCommand):
    help = "Run Telegram OTP bot"

    def handle(self, *args, **options):
        run_bot()
