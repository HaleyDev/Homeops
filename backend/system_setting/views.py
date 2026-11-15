from rest_framework.exceptions import ValidationError
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet

from backend.api import ApiResponseMixin, ok

from .models import LLMModel, LLMProvider, ModelType
from .permissions import IsSuperuser
from .serializers import LLMModelSerializer, LLMProviderSerializer, SelectionSerializer
from .services import SelectionError, clear_selection, select_model


class LLMProviderViewSet(ApiResponseMixin, ModelViewSet):
    queryset = LLMProvider.objects.all()
    serializer_class = LLMProviderSerializer
    permission_classes = [IsSuperuser]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)

    def perform_destroy(self, instance):
        if instance.models.filter(selected_for__isnull=False).exists():
            raise ValidationError(
                "This provider contains the currently selected model. "
                "Change the selection first."
            )
        instance.delete()

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return ok(message="供应商已删除。")


class LLMModelViewSet(ApiResponseMixin, ModelViewSet):
    queryset = LLMModel.objects.select_related("provider").all()
    serializer_class = LLMModelSerializer
    permission_classes = [IsSuperuser]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def perform_destroy(self, instance):
        if instance.selected_for is not None:
            raise ValidationError(
                "The currently selected model cannot be deleted. "
                "Change the selection first."
            )
        instance.delete()

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return ok(message="模型已删除。")


class SelectionListView(APIView):
    permission_classes = [IsSuperuser]

    def get(self, request):
        selections = []
        for category in ModelType:
            model = (
                LLMModel.objects.select_related("provider")
                .filter(selected_for=category.value)
                .first()
            )
            selections.append(
                {
                    "category": category.value,
                    "label": category.label,
                    "model": LLMModelSerializer(model).data if model else None,
                }
            )
        return ok(selections)


class SelectionDetailView(APIView):
    permission_classes = [IsSuperuser]

    @staticmethod
    def _validate_category(category):
        if category not in ModelType.values:
            raise ValidationError("Unsupported model category.")

    def put(self, request, category):
        self._validate_category(category)
        serializer = SelectionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            model = select_model(category, serializer.validated_data["model_id"])
        except SelectionError as exc:
            raise ValidationError(str(exc)) from exc
        return ok(
            LLMModelSerializer(model).data,
            message="当前模型已更新，将从下一轮对话开始生效。",
        )

    def delete(self, request, category):
        self._validate_category(category)
        try:
            clear_selection(category)
        except SelectionError as exc:
            raise ValidationError(str(exc)) from exc
        return ok(message="当前模型选择已清除。")
