from django.core.management.base import BaseCommand

from knowledge.services.vectorization import recover_stale_documents


class Command(BaseCommand):
    help = "重新投递长期未认领的文档，并将僵死向量化任务标记为失败。"

    def handle(self, *args, **options):
        result = recover_stale_documents()
        self.stdout.write(
            self.style.SUCCESS(
                "对账完成：重新投递 {redispatched} 篇，标记中断 {processing_failed} 篇。".format(
                    **result
                )
            )
        )
