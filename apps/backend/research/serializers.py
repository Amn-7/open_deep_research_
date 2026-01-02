from rest_framework import serializers
from .models import ResearchSession


class StartResearchSerializer(serializers.Serializer):
    query = serializers.CharField()
    parent_research_id = serializers.UUIDField(required=False, allow_null=True)


class ContinueResearchSerializer(serializers.Serializer):
    query = serializers.CharField()


class ResearchSessionListSerializer(serializers.ModelSerializer):
    class Meta:
        model = ResearchSession
        fields = ["id", "original_query", "status", "trace_id", "parent", "created_at", "updated_at"]
