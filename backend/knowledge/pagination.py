from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class KnowledgePagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100

    def get_page_size(self, request):
        raw_page_size = request.query_params.get(self.page_size_query_param)
        if raw_page_size is None:
            return self.page_size
        try:
            page_size = int(raw_page_size)
        except (TypeError, ValueError) as exc:
            raise ValidationError({"page_size": "分页大小必须是正整数。"}) from exc
        if page_size < 1:
            raise ValidationError({"page_size": "分页大小必须是正整数。"})
        return min(page_size, self.max_page_size)

    def paginate_queryset(self, queryset, request, view=None):
        try:
            return super().paginate_queryset(queryset, request, view=view)
        except NotFound as exc:
            raise ValidationError({"page": "页码必须是有效的正整数。"}) from exc

    def get_paginated_response(self, data):
        return Response(
            {
                "items": data,
                "total": self.page.paginator.count,
                "page": self.page.number,
                "page_size": self.get_page_size(self.request),
            }
        )
