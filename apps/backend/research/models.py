import uuid
from django.conf import settings
from django.db import models


class ResearchSession(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING"
        RUNNING = "RUNNING"
        COMPLETED = "COMPLETED"
        FAILED = "FAILED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="research_sessions",
    )

    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="children",
    )

    original_query = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)

    # LangSmith trace id
    trace_id = models.CharField(max_length=128, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.id} - {self.status}"


class ResearchSummary(models.Model):
    session = models.OneToOneField(
        ResearchSession, on_delete=models.CASCADE, related_name="summary"
    )
    summary = models.TextField()

    created_at = models.DateTimeField(auto_now_add=True)


class ResearchReasoning(models.Model):
    """
    High-level reasoning only (plan, why sources chosen, what was skipped).
    NO raw chain-of-thought.
    """
    session = models.OneToOneField(
        ResearchSession, on_delete=models.CASCADE, related_name="reasoning"
    )
    reasoning = models.TextField()

    created_at = models.DateTimeField(auto_now_add=True)


class ResearchReport(models.Model):
    session = models.OneToOneField(
        ResearchSession, on_delete=models.CASCADE, related_name="report"
    )
    report = models.TextField()
    sources = models.JSONField(default=list)  # list of {title,url, ...} or similar

    created_at = models.DateTimeField(auto_now_add=True)


class UploadedDocument(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    session = models.ForeignKey(
        ResearchSession, on_delete=models.CASCADE, related_name="documents"
    )

    file = models.FileField(upload_to="research_uploads/")
    filename = models.CharField(max_length=255)

    extracted_text = models.TextField(blank=True, default="")
    extracted_summary = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)


class ResearchCost(models.Model):
    session = models.OneToOneField(
        ResearchSession, on_delete=models.CASCADE, related_name="cost"
    )

    # tokens
    input_tokens = models.IntegerField(default=0)
    output_tokens = models.IntegerField(default=0)
    total_tokens = models.IntegerField(default=0)

    # money
    estimated_cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)

    # model info (useful for audits)
    model_name = models.CharField(max_length=128, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
