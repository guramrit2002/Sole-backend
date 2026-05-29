import re
from django.core.management.base import BaseCommand
from collection.models import Collection


def _parse_price(price_str):
    if not price_str:
        return 0.0
    cleaned = re.sub(r'[^\d.]', '', str(price_str))
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


class Command(BaseCommand):
    help = 'Backfill total_shoes and total_worth for all collections'

    def handle(self, *args, **options):
        updated = 0
        for coll in Collection.objects.prefetch_related('shoes').all():
            shoes = coll.shoes.all()
            total_shoes = shoes.count()
            total_worth = round(sum(_parse_price(s.price) for s in shoes), 2)
            Collection.objects.filter(pk=coll.pk).update(
                total_shoes=total_shoes,
                total_worth=total_worth,
            )
            updated += 1
        self.stdout.write(self.style.SUCCESS(f'Backfilled {updated} grail(s).'))
