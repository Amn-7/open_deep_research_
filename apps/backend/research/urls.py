from django.urls import path
from . import views

urlpatterns = [
    path("start", views.start_research, name="start-research"),
    path("history", views.research_history, name="research-history"),
    path("<uuid:research_id>", views.research_detail, name="research-detail"),
    path("<uuid:research_id>/upload", views.upload_document, name="upload-document"),
    path("<uuid:research_id>/continue", views.continue_research, name="continue-research"),
]
