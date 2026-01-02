import os

from django.contrib.auth import get_user_model
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework import status

from .models import ResearchSession, UploadedDocument
from .serializers import (
    ContinueResearchSerializer,
    ResearchSessionListSerializer,
    StartResearchSerializer,
)
from .tasks import process_uploaded_document, run_research  # ✅ use real task (remove ping_task)


def _get_or_create_dev_user():
    """
    TEMP for development only.
    Real auth later. For now we need a user_id for DB.
    """
    User = get_user_model()
    user, _ = User.objects.get_or_create(
        username="devuser",
        defaults={"email": "dev@local"},
    )
    return user


@api_view(["POST"])
def start_research(request):
    ser = StartResearchSerializer(data=request.data)
    ser.is_valid(raise_exception=True)

    user = _get_or_create_dev_user()

    parent_id = ser.validated_data.get("parent_research_id")
    parent = None
    if parent_id:
        parent = ResearchSession.objects.filter(id=parent_id, user=user).first()
        if not parent:
            return Response(
                {"error": "parent_research_id not found"},
                status=status.HTTP_400_BAD_REQUEST,
            )

    session = ResearchSession.objects.create(
        user=user,
        parent=parent,
        original_query=ser.validated_data["query"],
        status=ResearchSession.Status.PENDING,
    )

    # ✅ queue async deep research
    run_research.delay(str(session.id))

    return Response(
        {"research_id": str(session.id), "status": session.status},
        status=status.HTTP_201_CREATED,
    )


@api_view(["GET"])
def research_history(request):
    user = _get_or_create_dev_user()
    qs = ResearchSession.objects.filter(user=user).order_by("-created_at")
    data = ResearchSessionListSerializer(qs, many=True).data
    return Response(data, status=status.HTTP_200_OK)


@api_view(["GET"])
def research_detail(request, research_id):
    user = _get_or_create_dev_user()
    session = ResearchSession.objects.filter(id=research_id, user=user).first()
    if not session:
        return Response({"error": "not found"}, status=status.HTTP_404_NOT_FOUND)

    report = getattr(session, "report", None)
    summary = getattr(session, "summary", None)
    reasoning = getattr(session, "reasoning", None)
    cost = getattr(session, "cost", None)

    return Response(
        {
            "id": str(session.id),
            "parent": str(session.parent_id) if session.parent_id else None,
            "original_query": session.original_query,
            "status": session.status,
            "trace_id": session.trace_id,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
            "report": report.report if report else "",
            "sources": report.sources if report else [],
            "summary": summary.summary if summary else "",
            "reasoning": reasoning.reasoning if reasoning else "",
            "token_usage": {
                "input_tokens": cost.input_tokens if cost else 0,
                "output_tokens": cost.output_tokens if cost else 0,
                "total_tokens": cost.total_tokens if cost else 0,
            },
            "estimated_cost_usd": str(cost.estimated_cost_usd) if cost else "0",
        },
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser])
def upload_document(request, research_id):
    user = _get_or_create_dev_user()
    session = ResearchSession.objects.filter(id=research_id, user=user).first()
    if not session:
        return Response({"error": "not found"}, status=status.HTTP_404_NOT_FOUND)

    uploaded = request.FILES.get("file")
    if not uploaded:
        return Response({"error": "file is required"}, status=status.HTTP_400_BAD_REQUEST)

    ext = os.path.splitext(uploaded.name)[1].lower()
    if ext not in {".pdf", ".txt"}:
        return Response({"error": "unsupported file type"}, status=status.HTTP_400_BAD_REQUEST)

    doc = UploadedDocument.objects.create(
        session=session,
        file=uploaded,
        filename=uploaded.name,
    )

    process_uploaded_document.delay(str(doc.id))

    return Response(
        {"document_id": str(doc.id), "status": "processing"},
        status=status.HTTP_201_CREATED,
    )


@api_view(["POST"])
def continue_research(request, research_id):
    user = _get_or_create_dev_user()
    parent = ResearchSession.objects.filter(id=research_id, user=user).first()
    if not parent:
        return Response({"error": "not found"}, status=status.HTTP_404_NOT_FOUND)

    ser = ContinueResearchSerializer(data=request.data)
    ser.is_valid(raise_exception=True)

    session = ResearchSession.objects.create(
        user=user,
        parent=parent,
        original_query=ser.validated_data["query"],
        status=ResearchSession.Status.PENDING,
    )

    run_research.delay(str(session.id))

    return Response(
        {
            "research_id": str(session.id),
            "parent_research_id": str(parent.id),
            "status": session.status,
        },
        status=status.HTTP_201_CREATED,
    )
